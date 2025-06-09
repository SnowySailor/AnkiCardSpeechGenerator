# Anki Card Speech Generator

A Python tool that generates high-quality audio for Anki flashcards using Google's Gemini AI text-to-speech capabilities. This tool supports multiple character voices, emotions, and configurable MP3 compression.

## Features

- **Multiple Voice Characters**: Configure different speakers with unique voice characteristics
- **Emotion Support**: Apply emotional context to speech generation
- **MP3 Compression**: Adjustable bitrate for file size optimization
- **Anki Integration**: Works with Anki card data from ankiconnect API
- **Character Management**: Easy addition of new voice characters
- **HTML Cleaning**: Automatically removes HTML tags from card content

## Installation

1. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Install FFmpeg** (required for MP3 conversion):
   - **macOS**: `brew install ffmpeg`
   - **Ubuntu/Debian**: `sudo apt install ffmpeg`
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

3. **Get Gemini API Key**:
   - Visit [Google AI Studio](https://ai.google.dev/)
   - Generate an API key
   - Set environment variable: `export GEMINI_API_KEY="your-api-key-here"`

## Quick Start

```python
from speech_generator import SpeechGenerator

# Initialize the generator
generator = SpeechGenerator(
    characters_file="characters.json",
    output_dir="audio_output",
    mp3_bitrate="128k"
)

# Example Anki card data
card = {
    "cardId": 1001,
    "fields": {
        "Front": {"value": "What is the capital of France?"},
        "Back": {"value": "Paris is the capital of France."},
        "Speaker": {"value": "Teacher"},
        "Emotion": {"value": "confident"},
        "Audio": {"value": ""}
    }
}

# Generate audio
audio_path = generator.generate(card)
print(f"Audio saved to: {audio_path}")
```

## Character Configuration

The `characters.json` file defines voice characteristics for different speakers:

```json
{
  "Teacher": {
    "speaker": "Orus",
    "promptPrefix": "As a patient teacher, explain concepts clearly and firmly:"
  },
  "Dr. Anya": {
    "speaker": "Kore",
    "promptPrefix": "As Dr. Anya, speak with scientific authority and enthusiasm:"
  }
}
```

### Available Gemini Voices

The tool supports 30 different voices from Gemini's TTS system:

| Voice Name | Characteristic | Voice Name | Characteristic |
|------------|----------------|------------|----------------|
| Zephyr | Bright | Puck | Upbeat |
| Kore | Firm | Fenrir | Excitable |
| Orus | Firm | Aoede | Breezy |
| Charon | Informative | Leda | Youthful |

[View complete voice list](https://ai.google.dev/gemini-api/docs/speech-generation#voice-options)

## Anki Card Fields

The generator expects Anki cards with these fields:

- **Speaker**: Character name (matches `characters.json` keys)
- **Emotion**: Emotional context (optional)
- **Audio**: Will be populated with generated audio path
- **Content Fields**: Any field containing text to be spoken (Front, Back, Question, Answer, etc.)

## Configuration Options

### MP3 Compression

Adjust audio quality and file size:

```python
# Set compression (bitrate options: "64k", "128k", "192k", "320k")
generator.set_compression("192k")  # Higher quality, larger files
generator.set_compression("64k")   # Lower quality, smaller files
```

### Adding New Characters

```python
generator.add_character(
    name="Storyteller",
    speaker="Schedar",
    prompt_prefix="As a captivating storyteller, narrate with dramatic flair:"
)
```

## Example Usage

Run the example script to see the tool in action:

```bash
python example_usage.py
```

This will:
1. Generate audio for sample cards
2. Demonstrate compression adjustment
3. Add a new character
4. Show error handling

## Supported Languages

Gemini TTS supports 24 languages including:
- English (US/India)
- Spanish, French, German
- Japanese, Korean, Chinese
- Arabic, Hindi, Bengali
- And more...

## API Usage

### Core Methods

```python
# Initialize
generator = SpeechGenerator(api_key="your-key", mp3_bitrate="128k")

# Generate audio for a card
audio_path = generator.generate(anki_card_dict)

# Adjust compression
generator.set_compression("192k")

# Add new character
generator.add_character("NewChar", "VoiceName", "Prompt prefix:")
```

### Error Handling

```python
try:
    audio_path = generator.generate(card)
except ValueError as e:
    print(f"Card data error: {e}")
except RuntimeError as e:
    print(f"Generation error: {e}")
```

## Integration with Anki

To use with your Anki collection:

1. Install [ankiconnect](https://github.com/FooSoft/anki-connect) addon
2. Query cards using ankiconnect API
3. Pass card data to `SpeechGenerator.generate()`
4. Update card's Audio field with returned path

```python
import requests

# Query Anki cards via ankiconnect
response = requests.post('http://localhost:8765', json={
    "action": "findCards",
    "params": {"query": "deck:MyDeck"}
})
card_ids = response.json()['result']

# Get card info
response = requests.post('http://localhost:8765', json={
    "action": "cardsInfo",
    "params": {"cards": card_ids}
})
cards = response.json()['result']

# Generate audio for each card
for card in cards:
    audio_path = generator.generate(card)
    # Update card with audio path...
```

## Troubleshooting

### Common Issues

1. **"ffmpeg not found"**:
   - Install ffmpeg and ensure it's in your PATH

2. **"API key not found"**:
   - Set `GEMINI_API_KEY` environment variable
   - Or pass `api_key` parameter to constructor

3. **"No text content found"**:
   - Ensure card has text in standard fields (Front, Back, etc.)
   - Check field names in your Anki card type

4. **"Character not found"**:
   - Add character to `characters.json`
   - Or use existing character names

### File Permissions

Ensure the output directory is writable:
```bash
chmod 755 audio_output/
```

## License

This project uses Google's Gemini AI service. Please review [Google's Terms of Service](https://ai.google.dev/terms) for API usage.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with example cards
5. Submit a pull request

## Support

For issues related to:
- **Gemini API**: Check [Google AI documentation](https://ai.google.dev/gemini-api/docs/speech-generation)
- **Anki Integration**: See [ankiconnect documentation](https://github.com/FooSoft/anki-connect)
- **This Tool**: Open an issue in this repository 