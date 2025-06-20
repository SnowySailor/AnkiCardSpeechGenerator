# Anki Card Speech Generator

A Python tool that generates high-quality audio for Anki flashcards using multiple text-to-speech providers. Features full AnkiConnect integration for automated deck processing with intelligent hash-based audio management.

## Features

- **AnkiConnect Integration**: Automatically process entire Anki decks
- **Hash-Based Audio Management**: Only regenerate audio when content changes
- **Multiple Voice Characters**: Configure different speakers with unique voice characteristics
- **Emotion Support**: Apply emotional context to speech generation
- **MP3 Compression**: Adjustable bitrate for file size optimization
- **Character Management**: Easy addition of new voice characters
- **HTML Cleaning**: Automatically removes HTML tags from card content
- **Extensible Architecture**: Abstract base class for easy provider integration

## Architecture

The tool uses an abstract base class `SpeechGenerator` with provider-specific implementations:

- **`SpeechGenerator`** (Abstract Base Class): Defines the common interface
- **`GeminiSpeechGenerator`**: Implementation using Google's Gemini AI TTS
- **`AnkiSpeechProcessor`**: Handles AnkiConnect integration and deck processing
- **Future providers**: Can be easily added by extending the base class

## Installation

1. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Install FFmpeg** (required for MP3 conversion):
   - **macOS**: `brew install ffmpeg`
   - **Ubuntu/Debian**: `sudo apt install ffmpeg`
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

3. **Install AnkiConnect Addon**:
   - Open Anki
   - Go to Tools → Add-ons → Get Add-ons
   - Enter code: `2055492159`
   - Restart Anki

## Quick Start

### Method 1: Interactive Mode (Recommended)

```bash
python process_anki_deck.py
```

This launches an interactive interface that will:
1. List all available decks
2. Let you select a deck
3. Preview the cards and field mapping
4. Process the deck with smart hash-based updates

### Method 2: Command Line

```bash
# List available decks
python process_anki_deck.py --list-decks

# Preview a deck without processing
python process_anki_deck.py "My Japanese Deck" --preview

# Process a deck
python process_anki_deck.py "My Japanese Deck"

# Force regenerate all audio
python process_anki_deck.py "My Japanese Deck" --force

# Custom field mapping
python process_anki_deck.py "My Deck" \
  --sentence-field "Text" \
  --speaker-field "Character" \
  --emotion-field "Mood"
```

### Method 3: Programmatic Usage

```python
from anki_speech_processor import AnkiSpeechProcessor
from speech_generator import create_default_generator

# Create processor
processor = AnkiSpeechProcessor(
    speech_generator=create_default_generator(mp3_bitrate="192k"),
    sentence_field="Sentence",
    speaker_field="Speaker",
    emotion_field="Emotion",
    audio_field="Audio"
)

# Process a deck
stats = processor.process_deck("My Japanese Deck")
processor.print_statistics(stats)
```

## Hash-Based Audio Management

The system uses intelligent hashing to determine when audio needs regeneration:

### Hash Components
- **Sentence content** (HTML-cleaned)
- **Speaker configuration** (voice, prompt prefix)
- **Emotion setting**
- **TTS provider** and settings
- **Audio bitrate**

### File Naming
Audio files are named using the format: `speech_{hash}.mp3`

Example: `speech_a1b2c3d4e5f6g7h8.mp3`

### Smart Updates
- ✅ **Regenerate**: When text, speaker, emotion, or settings change
- ⏭️ **Skip**: When hash matches existing audio file
- 🔄 **Force mode**: Regenerate all audio regardless of hash

## Character Configuration

The `characters.json` file defines voice characteristics for different speakers:

```json
{
  "Teacher": {
    "speaker": "Orus",
    "promptPrefix": "As a patient teacher, explain concepts clearly and firmly:"
  },
  "Student": {
    "speaker": "Leda",
    "promptPrefix": "As an eager student, speak with youthful curiosity:"
  },
  "Narrator": {
    "speaker": "Charon",
    "promptPrefix": "As a knowledgeable narrator, speak clearly and informatively:"
  }
}
```

### Available Gemini Voices

| Voice Name | Characteristic | Voice Name | Characteristic |
|------------|----------------|------------|----------------|
| Zephyr | Bright | Puck | Upbeat |
| Kore | Firm | Fenrir | Excitable |
| Orus | Firm | Aoede | Breezy |
| Charon | Informative | Leda | Youthful |

[View complete voice list](https://ai.google.dev/gemini-api/docs/speech-generation#voice-options)

## Anki Card Fields

### Required Fields
- **Sentence**: Text to be converted to speech (configurable name)
- **Speaker**: Character name (matches `characters.json` keys)
- **Audio**: Field to store generated audio filename

### Optional Fields
- **Emotion**: Emotional context for speech generation

### Field Mapping
You can customize field names using command-line arguments:

```bash
python process_anki_deck.py "My Deck" \
  --sentence-field "Japanese" \
  --speaker-field "Voice" \
  --bitrate "192k"
```

## Usage Examples

### Process Language Learning Deck
```bash
# Japanese learning deck with custom fields
python process_anki_deck.py "Japanese::Core 2k" \
  --sentence-field "Japanese" \
  --speaker-field "Voice" \
  --bitrate "192k"
```

### Preview Before Processing
```bash
# Check field mapping first
python process_anki_deck.py "My Deck" --preview

# Then process
python process_anki_deck.py "My Deck"
```

### Batch Processing Multiple Decks
```python
from anki_speech_processor import AnkiSpeechProcessor

processor = AnkiSpeechProcessor()
decks = ["Japanese::Vocabulary", "Japanese::Grammar", "Japanese::Kanji"]

for deck_name in decks:
    print(f"Processing {deck_name}...")
    stats = processor.process_deck(deck_name)
    processor.print_statistics(stats)
```

## Configuration Options

### MP3 Compression
```bash
# Different quality levels
python process_anki_deck.py "My Deck" --bitrate "64k"   # Smaller files
python process_anki_deck.py "My Deck" --bitrate "320k"  # Higher quality
```

### Force Regeneration
```bash
# Regenerate all audio files
python process_anki_deck.py "My Deck" --force
```

## AnkiConnect Setup

### Installation
1. Open Anki
2. Tools → Add-ons → Get Add-ons
3. Enter code: `2055492159`
4. Restart Anki

### Verification
```bash
# Test AnkiConnect connection
curl http://localhost:8765 -X POST -d '{"action": "version", "version": 6}'
```

Should return: `{"result": 6, "error": null}`

## Troubleshooting

### Common Issues

1. **"Cannot connect to AnkiConnect"**:
   - Ensure Anki is running
   - Verify AnkiConnect addon is installed and enabled
   - Check that port 8765 is not blocked

2. **"No cards found in deck"**:
   - Verify deck name spelling (case-sensitive)
   - Use `--list-decks` to see available decks
   - Check that deck contains cards

3. **"No Sentence field found"**:
   - Use `--preview` to see available fields
   - Specify correct field with `--sentence-field`

4. **"ffmpeg not found"**:
   - Install ffmpeg and ensure it's in your PATH

### Field Mapping Issues
```bash
# Preview to identify fields
python process_anki_deck.py "My Deck" --preview

# Common field name variations
--sentence-field "Text"        # For "Text" field
--sentence-field "Front"       # For "Front" field
--sentence-field "Japanese"    # For language-specific fields
```

### Performance Tips
- Use lower bitrates (64k, 128k) for faster processing
- Process smaller decks first to test configuration
- Use preview mode to verify field mapping before bulk processing

## Integration Examples

### Language Learning Workflow
```bash
# 1. Preview new cards
python process_anki_deck.py "Japanese::Daily" --preview

# 2. Process with high quality for study
python process_anki_deck.py "Japanese::Daily" --bitrate "192k"

# 3. Update only changed cards (automatic)
python process_anki_deck.py "Japanese::Daily"
```

### Podcast/Story Deck
```python
# Add storyteller character
processor = AnkiSpeechProcessor()
processor.speech_generator.add_character(
    name="Storyteller",
    speaker="Schedar",
    prompt_prefix="As a captivating storyteller, narrate with dramatic flair:"
)

# Process story deck
stats = processor.process_deck("Stories::Fairy Tales")
```

## API Reference

### AnkiSpeechProcessor Methods

```python
# Initialize
processor = AnkiSpeechProcessor(
    speech_generator=None,  # Optional custom generator
    sentence_field="Sentence",
    speaker_field="Speaker", 
    emotion_field="Emotion",
    audio_field="Audio"
)

# Core methods
processor.list_decks()                    # Get available decks
processor.get_card_preview(deck_name)     # Preview cards
processor.process_deck(deck_name)         # Process entire deck
processor.print_statistics(stats)        # Show results
```

## License

This project uses Google's Gemini AI service. Please review [Google's Terms of Service](https://ai.google.dev/terms) for API usage.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with example cards
5. Submit a pull request

### Adding New TTS Providers

We welcome contributions for additional TTS providers! Follow the abstract class pattern:

1. Extend `SpeechGenerator` abstract class
2. Implement `_generate_audio_data()` method
3. Add provider to factory function
4. Update documentation
5. Add tests and examples

## Support

For issues related to:
- **Gemini API**: Check [Google AI documentation](https://ai.google.dev/gemini-api/docs/speech-generation)
- **AnkiConnect**: See [AnkiConnect documentation](https://github.com/FooSoft/anki-connect)
- **This Tool**: Open an issue in this repository 