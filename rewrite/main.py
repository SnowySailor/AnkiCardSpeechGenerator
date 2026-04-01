import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
ENV_FILE = BASE_DIR / "env.json"
REPLACEMENTS_FILE = BASE_DIR / "replacements.json"


def load_api_key() -> str:
    try:
        with open(ENV_FILE) as f:
            return json.load(f)["geminiApiKey"]
    except (FileNotFoundError, KeyError) as e:
        sys.exit(f"Could not load API key from {ENV_FILE}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate TTS audio for Anki cards and store them via AnkiConnect."
    )
    parser.add_argument("deck_name", help="Name of the Anki deck to process")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which cards need audio without calling the TTS API",
    )
    args = parser.parse_args()

    import replacements as rpl
    from anki import AnkiClient
    from audio.gemini import GeminiAudioGenerator
    from processor import Processor

    api_key = load_api_key()
    replacements_data = rpl.load(REPLACEMENTS_FILE)
    anki = AnkiClient()
    generator = GeminiAudioGenerator(api_key)

    processor = Processor(
        anki=anki,
        generator=generator,
        replacements_data=replacements_data,
        dry_run=args.dry_run,
    )
    processor.run(args.deck_name)


if __name__ == "__main__":
    main()
