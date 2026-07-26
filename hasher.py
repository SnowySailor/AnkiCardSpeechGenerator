import hashlib
import json

HASH_VERSION = 3
SPEAKER = "Kore"
PROVIDER = "GeminiAudioGenerator"
BITRATE = "128k"
SPEED = 1.0


def compute(
    clean_sentence: str,
    applicable_replacements: list[tuple[str, str]],
    applicable_hints: list[tuple[str, str]] | None = None,
) -> str:
    """Return a 16-character hex hash for the sentence, replacements, and hints."""
    data = {
        "version": HASH_VERSION,
        "sentence": clean_sentence,
        "speaker": SPEAKER,
        "provider": PROVIDER,
        "bitrate": BITRATE,
        "speed": SPEED,
        "replacements": [[orig, reading] for orig, reading in applicable_replacements],
        "hints": [[orig, reading] for orig, reading in (applicable_hints or [])],
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
