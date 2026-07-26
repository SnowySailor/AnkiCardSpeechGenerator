import re
from dataclasses import dataclass
from pathlib import Path

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


class Processor:
    def __init__(
        self,
        anki: AnkiClient,
        generator: AudioGenerator,
        replacements_data: dict,
        hints_data: dict,
        dry_run: bool = False,
    ):
        self.anki = anki
        self.generator = generator
        self.replacements_data = replacements_data
        self.hints_data = hints_data
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

        for i, pc in enumerate(to_generate, 1):
            prefix = f"[{i}/{len(to_generate)}]"
            print(f"{prefix} {pc.spoken_text[:60]}")
            try:
                mp3_bytes = self.generator.generate(pc.spoken_text, pc.prompt)
            except Exception as e:
                print(f"  ERROR generating audio: {e}")
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
                print(f"  ERROR updating Anki: {e}")
                continue

            print(f"  -> {pc.audio_filename}")

        print("Done.")
