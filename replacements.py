import json
import re


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_source(source: str) -> tuple[str | None, str | None, list[str]]:
    """Parse a Source field value into (manga, volume, pages).

    Examples:
      ""          -> (None, None, [])
      "INS"       -> ("INS", None, [])
      "INS V1"    -> ("INS", "V1", [])
      "INS V1 P11"     -> ("INS", "V1", ["P11"])
      "INS V1 P11,12"  -> ("INS", "V1", ["P11", "P12"])
    """
    parts = source.strip().split()
    manga = parts[0] if len(parts) >= 1 else None
    volume = parts[1] if len(parts) >= 2 else None
    pages: list[str] = []
    if len(parts) >= 3:
        page_str = parts[2]  # e.g. "P11,12"
        # Extract leading prefix (e.g. "P") and comma-separated numbers
        m = re.match(r"([A-Za-z]*)(\d[\d,]*)", page_str)
        if m:
            prefix = m.group(1)  # usually "P"
            numbers = m.group(2).split(",")
            pages = [f"{prefix}{n}" for n in numbers]
    return manga, volume, pages


def get_applicable(
    replacements_data: dict, clean_sentence: str, source_value: str
) -> list[tuple[str, str]]:
    """Return a sorted list of (original, reading) pairs that apply to this sentence."""
    collected: dict[str, str] = {}

    def _collect(mapping: dict) -> None:
        for original, reading in mapping.items():
            if original in clean_sentence:
                collected[original] = reading

    # Global replacements
    if "*" in replacements_data:
        _collect(replacements_data["*"])

    manga, volume, pages = _parse_source(source_value)

    if manga and manga in replacements_data:
        manga_data = replacements_data[manga]
        # Manga-level global
        if "*" in manga_data:
            _collect(manga_data["*"])

        if volume and volume in manga_data:
            volume_data = manga_data[volume]
            # Volume-level global (if present)
            if "*" in volume_data:
                _collect(volume_data["*"])
            # Page-specific
            for page in pages:
                if page in volume_data:
                    _collect(volume_data[page])

    return sorted(collected.items())


def parse_pairs(field_value: str) -> list[tuple[str, str]]:
    """Parse a card field (Replacements or Hints) into (original, reading) pairs.

    Format: "[search]:[pronunciation],[search]:[pronunciation]"
    Spaces around commas are stripped.
    """
    if not field_value.strip():
        return []
    pairs = []
    for item in field_value.split(","):
        item = item.strip()
        if ":" not in item:
            continue
        original, reading = item.split(":", 1)
        pairs.append((original.strip(), reading.strip()))
    return pairs


def apply_readings(clean_sentence: str, applicable: list[tuple[str, str]]) -> str:
    """Hard-substitute each matched word with its kana reading in the spoken text.

    Gemini TTS has no phoneme override and a natural-language prompt can't reliably
    beat the model's lexical prior (e.g. 明日→あす, 曲が→まが). Replacing the surface
    form with kana removes the kanji entirely, so the reading is deterministic.

    Longest originals are substituted first so compound names (e.g. 明日小路) are
    consumed before their overlapping sub-parts (明日, 小路), which would otherwise
    clobber the compound. Readings are kana, so they never reintroduce a kanji
    original and can't cascade into a later substitution. Returns the sentence
    unchanged when there are no replacements.
    """
    text = clean_sentence
    for original, reading in sorted(applicable, key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(original, reading)
    return text


def build_pronunciation_prompt(applicable: list[tuple[str, str]]) -> str:
    """Japanese steering prompt telling the Gemini TTS voice which readings to use.

    Used for soft Hints: returned as the `prompt` field on SynthesisInput, it steers
    delivery but is never spoken. Empty string when there are no hints (plain synthesis).
    """
    if not applicable:
        return ""
    lines = "\n".join(f"・「{original}」は「{reading}」と読む" for original, reading in applicable)
    return (
        "以下の文章を、自然で落ち着いたナレーションとして一度だけ読み上げてください。"
        "次の語句は必ず指定の読み方で発音してください（一般的な読みと異なる場合も指定を優先）：\n"
        f"{lines}"
    )
