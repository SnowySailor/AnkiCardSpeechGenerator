#!/usr/bin/env python3
"""
Process an entire Anki deck to generate speech audio.
This script uses AnkiConnect to pull cards, generate audio with hash-based filenames,
and update the cards back to Anki.
"""

import os
import argparse
from anki_speech_processor import AnkiSpeechProcessor, AnkiConnectError
from speech_generator import GeminiSpeechGenerator, create_speech_generator
import traceback


def main():
    parser = argparse.ArgumentParser(description='Process Anki deck to generate speech audio')
    parser.add_argument('deck_name', help='Name of the Anki deck to process')
    parser.add_argument('--preview', action='store_true', 
                       help='Preview cards without generating audio')
    parser.add_argument('--force', action='store_true',
                       help='Force regenerate all audio files')
    parser.add_argument('--sentence-field', default='Expression',
                       help='Name of field containing text to speak (default: Expression)')
    parser.add_argument('--speaker-field', default='Speaker',
                       help='Name of field containing speaker name (default: Speaker)')
    parser.add_argument('--emotion-field', default='Emotion',
                       help='Name of field containing emotion (default: Emotion)')
    parser.add_argument('--audio-field', default='Audio',
                       help='Name of field to store audio filename (default: Audio)')
    parser.add_argument('--bitrate', default='128k',
                       choices=['64k', '128k', '192k', '320k'],
                       help='MP3 bitrate (default: 128k)')
    parser.add_argument('--speed', type=float, default=1.0,
                       help='Audio speed multiplier (default: 1.0 for 100%% speed)')
    parser.add_argument('--provider', default='gemini',
                       choices=['gemini'],
                       help='TTS provider (default: gemini)')
    parser.add_argument('--replacements', default='replacements.json',
                        help='Path to pronunciation replacements JSON file (default: replacements.json)')
    parser.add_argument('--list-decks', action='store_true',
                       help='List all available decks and exit')
    parser.add_argument('--keep-local-files', action='store_true',
                       help='Keep local audio files after storing in Anki (default: delete local files)')
    parser.add_argument('--batch-request', action='store_true',
                       help='Use Gemini Batch API to submit all card requests at once')
    parser.add_argument('--ignore-failed-log', action='store_true',
                        help='Ignore failed_to_generate_log and retry all cards')

    args = parser.parse_args()

    # Validate speed parameter
    if args.speed <= 0:
        print("❌ Error: Speed multiplier must be positive")
        return 1

    try:
        # Create speech generator
        speech_generator = create_speech_generator(
            provider=args.provider,
            mp3_bitrate=args.bitrate,
            speed_multiplier=args.speed
        )

        if args.batch_request:
            print("⏳ Batch mode enabled: checking for pending Gemini batch jobs...")
            speech_generator.wait_for_pending_batches()

        # Create processor
        processor = AnkiSpeechProcessor(
            speech_generator=speech_generator,
            sentence_field=args.sentence_field,
            speaker_field=args.speaker_field,
            emotion_field=args.emotion_field,
            audio_field=args.audio_field,
            keep_local_files=args.keep_local_files,
            replacements_file=args.replacements,
            batch_mode=args.batch_request
        )

        # List decks if requested
        if args.list_decks:
            print("Available decks:")
            decks = processor.list_decks()
            for i, deck in enumerate(decks, 1):
                print(f"  {i}. {deck}")
            return 0

        # Preview mode
        if args.preview:
            print(f"🔍 Preview mode: {args.deck_name}")
            processor.get_card_preview(args.deck_name, limit=10)
            return 0

        # Process the deck
        print(f"🚀 Processing deck: {args.deck_name}")
        print(f"📊 Provider: {args.provider}")
        print(f"🎵 Bitrate: {args.bitrate}")
        print(f"⏩ Speed: {args.speed}x ({args.speed*100:.0f}%)")
        print(f"📦 Batch mode: {'Enabled' if args.batch_request else 'Disabled'}")
        print(f"📝 Sentence field: {args.sentence_field}")
        print(f"🎭 Speaker field: {args.speaker_field}")
        print(f"😊 Emotion field: {args.emotion_field}")
        print(f"🔊 Audio field: {args.audio_field}")
        print(f"📖 Replacements file: {args.replacements}")
        print(f"🚫 Ignore failed log: {'Yes' if args.ignore_failed_log else 'No'}")
        print(f"💾 Keep local files: {'Yes' if args.keep_local_files else 'No'}")

        if args.force:
            print("⚠️ Force mode: Will regenerate ALL audio files")

        # Confirm before processing
        confirm = input(f"\nProceed with processing? (y/N): ").strip().lower()
        if confirm != 'y':
            print("Aborted.")
            return 0

        # Process the deck
        stats = processor.process_deck(
            args.deck_name,
            force_regenerate=args.force,
            use_batch=args.batch_request,
            ignore_failed_log=args.ignore_failed_log
        )
        processor.print_statistics(stats)

        return 0

    except AnkiConnectError as e:
        print(f"❌ AnkiConnect Error: {e}")
        print("\nMake sure:")
        print("1. Anki is running")
        print("2. AnkiConnect addon is installed")
        print("3. AnkiConnect is enabled in Anki")
        return 1

    except Exception as e:
        print(traceback.format_exc())
        print(f"❌ Error: {e}")
        return 1


def interactive_mode():
    """
    Interactive mode for easier deck processing.
    """
    print("🎤 Anki Speech Generator - Interactive Mode")
    print("=" * 50)

    try:
        # Create processor with defaults
        processor = AnkiSpeechProcessor(replacements_file="replacements.json")

        # List available decks
        print("\n📚 Available decks:")
        decks = processor.list_decks()
        for i, deck in enumerate(decks, 1):
            print(f"  {i}. {deck}")

        # Get user choice
        while True:
            try:
                choice = input(f"\nSelect deck (1-{len(decks)}) or 'q' to quit: ").strip()
                if choice.lower() == 'q':
                    return

                deck_idx = int(choice) - 1
                if 0 <= deck_idx < len(decks):
                    selected_deck = decks[deck_idx]
                    break
                else:
                    print("Invalid selection. Try again.")
            except ValueError:
                print("Please enter a number or 'q'.")

        # Preview cards
        print(f"\n🔍 Previewing deck: {selected_deck}")
        processor.get_card_preview(selected_deck)

        # Confirm processing
        confirm = input(f"\nProcess deck '{selected_deck}'? (y/N): ").strip().lower()
        if confirm == 'y':
            stats = processor.process_deck(selected_deck)
            processor.print_statistics(stats)
        else:
            print("Processing cancelled.")

    except AnkiConnectError as e:
        print(f"❌ AnkiConnect Error: {e}")
        print("Make sure Anki is running with AnkiConnect addon installed.")

    except Exception as e:
        print(traceback.format_exc())
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    # If no arguments provided, run interactive mode
    import sys
    if len(sys.argv) == 1:
        interactive_mode()
    else:
        exit(main()) 