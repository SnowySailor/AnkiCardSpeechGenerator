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


def apply_ssml(clean_sentence: str, applicable: list[tuple[str, str]]) -> str:
    """Wrap matched words with SSML phoneme tags. Returns plain text if no replacements."""
    if not applicable:
        return clean_sentence
    text = clean_sentence
    for original, reading in applicable:
        text = text.replace(
            original,
            f'<phoneme alphabet="yomigana" ph="{reading}">{original}</phoneme>',
        )
    return text
