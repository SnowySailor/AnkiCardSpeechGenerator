import os
import re
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import replacements as rpl
import hasher
from anki import AnkiClient
from audio.base import AudioGenerator

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
    return f"{minutes}m{seconds:02d}s" if minutes else f"{seconds}s"


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
        generator: AudioGenerator,
        replacements_data: dict,
        hints_data: dict,
        workers: int = 1,
        dry_run: bool = False,
    ):
        self.anki = anki
        self.generator = generator
        self.replacements_data = replacements_data
        self.hints_data = hints_data
        self.workers = workers
        self.dry_run = dry_run
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def run(self, deck_name: str) -> None:
        print(f"Fetching cards from deck: {deck_name}")
        card_ids = self.anki.find_cards(deck_name)
        print(f"Found {len(card_ids)} cards. Loading card info...")
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
            print(f"Skipped {skipped_empty} cards with empty sentences.")

        to_generate = [
            pc for pc in processable
            if _needs_generation(pc)
        ]
        to_skip = len(processable) - len(to_generate)

        print(f"{to_skip} cards already up-to-date, {len(to_generate)} need audio generation.")

        if self.dry_run:
            for pc in to_generate:
                print(f"  [dry-run] {pc.audio_filename}  {pc.spoken_text[:60]}")
            return

        self._generate_all(to_generate)

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
            console.print(Text.assemble((prefix, "dim"), " ", *parts))

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

                        output_path = OUTPUT_DIR / pc.audio_filename
                        output_path.write_bytes(mp3_bytes)

                        try:
                            self.anki.store_media_file(pc.audio_filename, mp3_bytes)
                            self.anki.update_note_field(
                                pc.note_id, AUDIO_FIELD, f"[sound:{pc.audio_filename}]"
                            )
                            if pc.force_regenerate:
                                self.anki.update_note_field(pc.note_id, REGENERATE_FIELD, "")
                        except Exception as e:
                            log(prefix, ("ERROR", "bold red"),
                                f" updating Anki for {pc.spoken_text[:40]}: {e}")
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
