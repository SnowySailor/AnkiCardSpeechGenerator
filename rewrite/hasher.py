import hashlib
import json

HASH_VERSION = 1
SPEAKER = "Kore"
PROVIDER = "GeminiAudioGenerator"
BITRATE = "128k"
SPEED = 1.0


def compute(
    clean_sentence: str,
    applicable_replacements: list[tuple[str, str]],
) -> str:
    """Return a 16-character hex hash for the given sentence and replacements."""
    data = {
        "version": HASH_VERSION,
        "sentence": clean_sentence,
        "speaker": SPEAKER,
        "provider": PROVIDER,
        "bitrate": BITRATE,
        "speed": SPEED,
        "replacements": [[orig, reading] for orig, reading in applicable_replacements],
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
