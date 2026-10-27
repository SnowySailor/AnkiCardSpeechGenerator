import argparse
import json
import sys
from pathlib import Path

REPLACEMENTS_FILE = Path("./replacements.json")
HINTS_FILE = Path("./hints.json")
ENV_FILE = Path("./env.json")


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
    parser.add_argument(
        "--limit",
        type=int,
        help="Generate at most this many cards this run",
    )
    args = parser.parse_args()

    import replacements as rpl
    from anki import AnkiClient
    from audio.gemini import GeminiBatch
    from processor import Processor

    replacements_data = rpl.load(REPLACEMENTS_FILE)
    hints_data = rpl.load(HINTS_FILE) if HINTS_FILE.exists() else {}
    anki = AnkiClient()

    processor = Processor(
        anki=anki,
        batch=GeminiBatch(load_api_key()),
        replacements_data=replacements_data,
        hints_data=hints_data,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    processor.run(args.deck_name)


if __name__ == "__main__":
    main()
