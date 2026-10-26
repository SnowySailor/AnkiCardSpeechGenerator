import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import replacements as rpl
import hasher
from anki import AnkiClient
from audio.base import AudioGenerator

if TYPE_CHECKING:
    from audio.gemini_batch import BatchStatus, GeminiBatch

SENTENCE_FIELD = "Expression"
AUDIO_FIELD = "AI Audio"
SOURCE_FIELD = "Source"
REGENERATE_FIELD = "Regenerate Audio"
CARD_REPLACEMENTS_FIELD = "Replacements"
CARD_HINTS_FIELD = "Reading Hints"
OUTPUT_DIR = Path(__file__).parent / "audio_output"

# In-flight requests turn yellow past SLOW_S (beyond Flex's 1-15 min target)
# and red past VERY_SLOW_S.
SLOW_S = 15 * 60
VERY_SLOW_S = 30 * 60
# A card in flight this long (wall clock) is abandoned and counted as failed.
# The generator gives up on its own well before this, so it only fires when its
# timeouts don't, e.g. the machine slept and the connection died silently.
STALL_TIMEOUT_S = 45 * 60

# Submitted batch jobs per deck, so a re-run resumes the job instead of paying
# for the same cards twice.
BATCH_STATE_FILE = Path(__file__).parent / "batch_state.json"
BATCH_POLL_S = 30

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _field(card: dict, name: str) -> str:
    return card.get("fields", {}).get(name, {}).get("value", "")


@dataclass
class ProcessableCard:
    note_id: int
    card_id: int
    clean_sentence: str
    applicable_replacements: list[tuple[str, str]]
    applicable_hints: list[tuple[str, str]]
    spoken_text: str
    prompt: str
    audio_hash: str
    audio_filename: str
    current_audio_value: str
    force_regenerate: bool


def _resolve(
    scoped: list[tuple[str, str]], card_field: str
) -> list[tuple[str, str]]:
    """Merge JSON-scoped pairs with a card field's pairs (card wins), sorted."""
    card_pairs = rpl.parse_pairs(card_field)
    if not card_pairs:
        return scoped
    merged = dict(scoped)
    merged.update(card_pairs)
    return sorted(merged.items())


def _build(
    card: dict, replacements_data: dict, hints_data: dict
) -> ProcessableCard | None:
    """Build a ProcessableCard from a raw AnkiConnect card dict.

    Returns None if the sentence is empty.
    """
    sentence_raw = _field(card, SENTENCE_FIELD)
    clean_sentence = _strip_html(sentence_raw)
    if not clean_sentence:
        return None

    source_value = _field(card, SOURCE_FIELD)

    # Hard replacements: substitute the reading into the spoken text (kanji removed).
    replacements = _resolve(
        rpl.get_applicable(replacements_data, clean_sentence, source_value),
        _field(card, CARD_REPLACEMENTS_FIELD),
    )
    spoken_text = rpl.apply_readings(clean_sentence, replacements)

    # Soft hints: nudge pronunciation via the prompt. Drop any hint whose word was
    # already substituted away, so it can't contradict a replacement in the prompt.
    hints = [
        (original, reading)
        for original, reading in _resolve(
            rpl.get_applicable(hints_data, clean_sentence, source_value),
            _field(card, CARD_HINTS_FIELD),
        )
        if original in spoken_text
    ]
    prompt = rpl.build_pronunciation_prompt(hints)

    audio_hash = hasher.compute(clean_sentence, replacements, hints)
    audio_filename = f"speech_{audio_hash}.mp3"
    current_audio_value = _field(card, AUDIO_FIELD)
    force_regenerate = bool(_field(card, REGENERATE_FIELD).strip())

    return ProcessableCard(
        note_id=card["note"],
        card_id=card["cardId"],
        clean_sentence=clean_sentence,
        applicable_replacements=replacements,
        applicable_hints=hints,
        spoken_text=spoken_text,
        prompt=prompt,
        audio_hash=audio_hash,
        audio_filename=audio_filename,
        current_audio_value=current_audio_value,
        force_regenerate=force_regenerate,
    )


def _needs_generation(card: ProcessableCard) -> bool:
    return card.force_regenerate or card.audio_hash not in card.current_audio_value


def _fmt_elapsed(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{seconds:02d}s" if minutes else f"{seconds}s"


def _log(console: Console, prefix: str, *parts) -> None:
    console.print(Text.assemble((prefix, "dim"), " ", *parts))


def _read_batch_state() -> dict:
    try:
        return json.loads(BATCH_STATE_FILE.read_text())
    except FileNotFoundError:
        return {}


def _write_batch_state(state: dict) -> None:
    if state:
        BATCH_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    else:
        BATCH_STATE_FILE.unlink(missing_ok=True)


@dataclass
class _InFlight:
    text: str
    started: float
    status: str = "starting"
    abandoned: bool = False


class _Tracker:
    """In-flight requests: written by worker threads, read by the live display."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[int, _InFlight] = {}

    def start(self, key: int, text: str) -> None:
        with self._lock:
            # Wall clock, so time the machine spends asleep still counts.
            self._items[key] = _InFlight(text, time.time())

    def update(self, key: int, status: str) -> None:
        with self._lock:
            item = self._items.get(key)
            if item and not item.abandoned:
                item.status = status

    def abandon(self, key: int) -> None:
        with self._lock:
            item = self._items[key]
            item.abandoned = True
            item.status = "abandoned, still holding a worker"

    def finish(self, key: int) -> None:
        with self._lock:
            self._items.pop(key, None)

    def stuck(self) -> int:
        """Workers still held by abandoned cards."""
        with self._lock:
            return sum(item.abandoned for item in self._items.values())

    def elapsed(self, key: int) -> float | None:
        with self._lock:
            item = self._items.get(key)
            return time.time() - item.started if item else None

    def snapshot(self) -> list[_InFlight]:
        with self._lock:
            return sorted(
                (_InFlight(i.text, i.started, i.status, i.abandoned)
                 for i in self._items.values()),
                key=lambda i: i.started,
            )


class Processor:
    def __init__(
        self,
        anki: AnkiClient,
        generator: AudioGenerator | None,
        replacements_data: dict,
        hints_data: dict,
        workers: int = 1,
        dry_run: bool = False,
        batch: "GeminiBatch | None" = None,
        limit: int | None = None,
    ):
        """Pass generator for the live (flex/standard) route, or batch for the
        batch route."""
        self.anki = anki
        self.generator = generator
        self.batch = batch
        self.replacements_data = replacements_data
        self.hints_data = hints_data
        self.workers = workers
        self.limit = limit
        self.dry_run = dry_run
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def run(self, deck_name: str) -> None:
        to_generate = self._cards_needing_audio(deck_name)

        if self.limit is not None and len(to_generate) > self.limit:
            print(f"--limit {self.limit}: only the first {self.limit} this run.")
            to_generate = to_generate[:self.limit]

        if self.dry_run:
            for pc in to_generate:
                print(f"  [dry-run] {pc.audio_filename}  {pc.spoken_text[:60]}")
            return

        if self.batch:
            self._run_batch(deck_name, to_generate)
        else:
            self._generate_all(to_generate)

    def _cards_needing_audio(
        self, deck_name: str, verbose: bool = True
    ) -> list[ProcessableCard]:
        say = print if verbose else (lambda *_: None)
        say(f"Fetching cards from deck: {deck_name}")
        card_ids = self.anki.find_cards(deck_name)
        say(f"Found {len(card_ids)} cards. Loading card info...")
        raw_cards = self.anki.cards_info(card_ids)

        processable = []
        skipped_empty = 0
        for raw in raw_cards:
            pc = _build(raw, self.replacements_data, self.hints_data)
            if pc is None:
                skipped_empty += 1
            else:
                processable.append(pc)

        if skipped_empty:
            say(f"Skipped {skipped_empty} cards with empty sentences.")

        to_generate = [
            pc for pc in processable
            if _needs_generation(pc)
        ]
        to_skip = len(processable) - len(to_generate)

        say(f"{to_skip} cards already up-to-date, {len(to_generate)} need audio generation.")
        return to_generate

    def _save(self, pc: ProcessableCard, mp3_bytes: bytes) -> None:
        """Write the audio locally and into Anki, and point the note at it."""
        (OUTPUT_DIR / pc.audio_filename).write_bytes(mp3_bytes)
        self.anki.store_media_file(pc.audio_filename, mp3_bytes)
        self.anki.update_note_field(
            pc.note_id, AUDIO_FIELD, f"[sound:{pc.audio_filename}]"
        )
        if pc.force_regenerate:
            self.anki.update_note_field(pc.note_id, REGENERATE_FIELD, "")

    def _generate_all(self, to_generate: list[ProcessableCard]) -> None:
        # Generation runs in worker threads; file and AnkiConnect writes stay on
        # this thread, so each card is saved as soon as its audio arrives.
        console = Console(highlight=False)
        tracker = _Tracker()
        total = len(to_generate)
        written = failed = abandoned = skipped = 0
        executor = ThreadPoolExecutor(max_workers=self.workers)
        pending = {
            executor.submit(self._generate_one, tracker, key, pc): (key, pc)
            for key, pc in enumerate(to_generate)
        }

        def render() -> Panel:
            now = time.time()
            table = Table.grid(padding=(0, 2), expand=True)
            table.add_column(justify="right", no_wrap=True)
            table.add_column(no_wrap=True)
            table.add_column(no_wrap=True, overflow="ellipsis", ratio=1)
            items = tracker.snapshot()
            for item in items:
                elapsed = now - item.started
                time_style = (
                    "red" if elapsed >= VERY_SLOW_S
                    else "yellow" if elapsed >= SLOW_S
                    else ""
                )
                status_style = (
                    "bold red" if item.abandoned
                    else "dim" if item.status.startswith("waiting")
                    else "yellow"
                )
                table.add_row(
                    Text(_fmt_elapsed(elapsed), style=time_style),
                    Text(item.status, style=status_style),
                    Text(item.text),
                )
            finished = written + failed
            queued = total - finished - len(items)
            title = (
                f"In flight {len(items)}/{self.workers} · {written} done · "
                f"{failed} failed · {max(queued, 0)} queued"
            )
            return Panel(table, title=title, title_align="left", border_style="blue")

        def log(prefix: str, *parts) -> None:
            _log(console, prefix, *parts)

        console.print(
            f"Generating with {self.workers} workers; results arrive as each finishes."
        )
        try:
            with Live(get_renderable=render, console=console,
                      refresh_per_second=2, transient=True):
                while pending:
                    done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                    for future in done:
                        _, pc = pending.pop(future)
                        prefix = f"[{written + failed + 1}/{total}]"
                        try:
                            mp3_bytes, elapsed = future.result()
                        except Exception as e:
                            log(prefix, ("ERROR", "bold red"),
                                f" generating audio for {pc.spoken_text[:40]}: {e}")
                            failed += 1
                            continue

                        try:
                            self._save(pc, mp3_bytes)
                        except Exception as e:
                            log(prefix, ("ERROR", "bold red"),
                                f" saving audio for {pc.spoken_text[:40]}: {e}")
                            failed += 1
                            continue

                        log(prefix, (pc.audio_filename, "cyan"), "  ",
                            pc.spoken_text[:60], (f"  {_fmt_elapsed(elapsed)}", "dim"))
                        written += 1

                    # A worker thread can't be killed, so a stalled card keeps
                    # its slot; stop waiting on it so the run can still finish.
                    for future, (key, pc) in list(pending.items()):
                        elapsed = tracker.elapsed(key)
                        if elapsed is None or elapsed < STALL_TIMEOUT_S:
                            continue
                        del pending[future]
                        tracker.abandon(key)
                        log(f"[{written + failed + 1}/{total}]", ("ERROR", "bold red"),
                            f" no response after {_fmt_elapsed(elapsed)}, abandoned: "
                            f"{pc.spoken_text[:40]}")
                        failed += 1
                        abandoned += 1

                    # With every worker held by an abandoned card, nothing queued
                    # can ever start; skip the rest rather than wait forever.
                    if pending and tracker.stuck() >= self.workers:
                        for future in pending:
                            future.cancel()
                        skipped = len(pending)
                        pending.clear()
                        console.print(Text.assemble(
                            ("ERROR", "bold red"),
                            f" all {self.workers} workers are stuck; skipped "
                            f"{skipped} queued cards. Re-run to pick them up.",
                        ))
        except KeyboardInterrupt:
            executor.shutdown(wait=False, cancel_futures=True)
            dropped = total - written - failed
            console.print(f"\nInterrupted: {written} written, {failed} failed, {dropped} dropped.")
            # Skip waiting on in-flight requests, which can take up to the
            # request timeout; everything finished is already in Anki.
            os._exit(130)

        summary = f"Done: {written} written, {failed} failed"
        console.print(summary + (f", {skipped} skipped." if skipped else "."))
        if abandoned:
            # Abandoned requests still occupy worker threads, which the
            # interpreter would otherwise wait on at exit.
            sys.stdout.flush()
            os._exit(1)
        executor.shutdown()

    def _generate_one(
        self, tracker: _Tracker, key: int, pc: ProcessableCard
    ) -> tuple[bytes, float]:
        tracker.start(key, pc.spoken_text)
        started = time.time()
        try:
            mp3_bytes = self.generator.generate(
                pc.spoken_text, pc.prompt,
                on_status=lambda status: tracker.update(key, status),
            )
            return mp3_bytes, time.time() - started
        finally:
            tracker.finish(key)

    def _run_batch(self, deck_name: str, to_generate: list[ProcessableCard]) -> None:
        console = Console(highlight=False)
        state = _read_batch_state()
        entry = state.get(deck_name)
        if entry:
            console.print(
                f"Resuming batch job {entry['job']} ({len(entry['keys'])} requests, "
                f"submitted {entry['submitted']}). Cards outside it wait for the next run."
            )
        elif not to_generate:
            return
        else:
            # One request per distinct audio: cards sharing a sentence share a hash.
            items = {}
            for pc in to_generate:
                items.setdefault(pc.audio_hash, (pc.spoken_text, pc.prompt))
            shared = len(to_generate) - len(items)
            console.print(
                f"Submitting a batch of {len(items)} requests"
                + (f" (+{shared} duplicate card{'s' if shared != 1 else ''})" if shared else "")
                + "..."
            )
            job_name = self.batch.submit(items, display_name=f"anki-{deck_name}")
            entry = {
                "job": job_name,
                "submitted": datetime.now().astimezone().isoformat(timespec="seconds"),
                "keys": list(items),
            }
            state[deck_name] = entry
            _write_batch_state(state)
            console.print(f"Submitted {job_name}.")

        status = self._wait_for_batch(console, entry)
        keep_job = False
        if status.succeeded:
            keep_job = self._collect_batch(console, deck_name, entry, status)
        else:
            reason = f": {status.error}" if status.error else ""
            console.print(Text.assemble(
                ("ERROR", "bold red"),
                f" batch job {status.state.lower()}{reason}. Re-run to submit again.",
            ))

        if not keep_job:
            state = _read_batch_state()
            state.pop(deck_name, None)
            _write_batch_state(state)

    def _wait_for_batch(self, console: Console, entry: dict) -> "BatchStatus":
        submitted = datetime.fromisoformat(entry["submitted"])
        status = self.batch.status(entry["job"])
        next_check = time.time() + BATCH_POLL_S
        note = ""

        def render() -> Panel:
            waited = (datetime.now().astimezone() - submitted).total_seconds()
            line = Text.assemble(
                (status.state.lower().replace("_", " "), "bold"),
                f" · {len(entry['keys'])} requests · submitted {_fmt_elapsed(waited)} ago"
                f" · next check in {max(0, int(next_check - time.time()))}s",
            )
            if note:
                line.append(f"\n{note}", style="yellow")
            return Panel(line, title=f"Batch {entry['job']}", title_align="left",
                         border_style="blue")

        try:
            with Live(get_renderable=render, console=console,
                      refresh_per_second=2, transient=True):
                while not status.done:
                    time.sleep(1)
                    if time.time() < next_check:
                        continue
                    try:
                        status = self.batch.status(entry["job"])
                        note = ""
                    except Exception as e:
                        note = f"status check failed, will retry: {e}"
                    next_check = time.time() + BATCH_POLL_S
        except KeyboardInterrupt:
            console.print(
                f"\nStopped waiting. {entry['job']} keeps running on Google's side; "
                "re-run the same command to collect it."
            )
            sys.exit(130)
        return status

    def _collect_batch(
        self, console: Console, deck_name: str, entry: dict, status: "BatchStatus"
    ) -> bool:
        """Save results into matching cards. Returns True if the job should be
        kept for another collection attempt (some saves to Anki failed)."""
        if not status.result_file:
            console.print(Text.assemble(
                ("ERROR", "bold red"),
                f" batch {status.state.lower()} but has no result file. Re-run to submit again.",
            ))
            return False
        console.print(f"Batch {status.state.lower()}; downloading results...")
        # Re-read the deck: cards edited since submission have a different hash
        # now and are left for the next run, and cards that got audio some other
        # way no longer need it.
        by_hash = defaultdict(list)
        for pc in self._cards_needing_audio(deck_name, verbose=False):
            by_hash[pc.audio_hash].append(pc)

        total = len(entry["keys"])
        written = failed = save_failed = unused = 0
        for i, (key, result) in enumerate(self.batch.results(status, entry["keys"]), 1):
            prefix = f"[{i}/{total}]"
            cards = by_hash.get(key, [])
            if isinstance(result, str):
                text = cards[0].spoken_text[:40] if cards else key
                _log(console, prefix, ("ERROR", "bold red"),
                     f" generating audio for {text}: {result}")
                failed += 1
                continue
            if not cards:
                unused += 1
                continue
            for pc in cards:
                try:
                    self._save(pc, result)
                except Exception as e:
                    _log(console, prefix, ("ERROR", "bold red"),
                         f" saving audio for {pc.spoken_text[:40]}: {e}")
                    save_failed += 1
                    continue
                _log(console, prefix, (pc.audio_filename, "cyan"), "  ",
                     pc.spoken_text[:60])
                written += 1

        summary = f"Done: {written} written, {failed + save_failed} failed"
        if unused:
            summary += f", {unused} results unused (card changed or already has audio)"
        console.print(summary + ".")
        if save_failed:
            console.print(
                f"Kept {entry['job']} so a re-run can retry the cards that failed to save."
            )
        return save_failed > 0
