# Anki Card Speech Generator

A Python tool that generates high-quality audio for Anki flashcards using multiple text-to-speech providers. Currently supports Google's Gemini AI with an extensible architecture for additional providers.

## Features

- **Multiple Voice Characters**: Configure different speakers with unique voice characteristics
- **Emotion Support**: Apply emotional context to speech generation
- **MP3 Compression**: Adjustable bitrate for file size optimization
- **Anki Integration**: Works with Anki card data from ankiconnect API
- **Character Management**: Easy addition of new voice characters
- **HTML Cleaning**: Automatically removes HTML tags from card content
- **Extensible Architecture**: Abstract base class for easy provider integration

## Architecture

The tool uses an abstract base class `SpeechGenerator` with provider-specific implementations:

- **`SpeechGenerator`** (Abstract Base Class): Defines the common interface
- **`GeminiSpeechGenerator`**: Implementation using Google's Gemini AI TTS
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

3. **Get Gemini API Key**:
   - Visit [Google AI Studio](https://ai.google.dev/)
   - Generate an API key
   - Set environment variable: `export GEMINI_API_KEY="your-api-key-here"`

## Quick Start

### Method 1: Direct Class Usage

```python
from speech_generator import GeminiSpeechGenerator

# Initialize the Gemini generator directly
generator = GeminiSpeechGenerator(
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

### Method 2: Factory Function

```python
from speech_generator import create_speech_generator

# Create using factory function
generator = create_speech_generator(
    provider="gemini",
    characters_file="characters.json",
    output_dir="audio_output",
    mp3_bitrate="128k"
)

audio_path = generator.generate(card)
```

### Method 3: Default Generator

```python
from speech_generator import create_default_generator

# Create default generator (currently Gemini)
generator = create_default_generator(
    characters_file="characters.json",
    output_dir="audio_output",
    mp3_bitrate="128k"
)

audio_path = generator.generate(card)
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

This will demonstrate:
1. Different initialization methods
2. Audio generation for sample cards
3. Compression adjustment
4. Character management
5. Error handling

## Supported Providers

### Current Providers

- **Gemini** (`gemini`): Google's Gemini AI TTS
  - 30 different voices
  - 24 language support
  - High-quality natural speech

### Adding New Providers

To add a new TTS provider, extend the `SpeechGenerator` abstract class:

```python
from speech_generator import SpeechGenerator

class CustomTTSGenerator(SpeechGenerator):
    def __init__(self, api_key, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        # Initialize your TTS client here
    
    def _generate_audio_data(self, text: str, speaker_name: str, emotion: str = "") -> bytes:
        # Implement your TTS provider logic here
        # Return WAV audio data as bytes
        pass
```

Then update the factory function to include your provider.

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
# Initialize (multiple options)
generator = GeminiSpeechGenerator(api_key="your-key")
generator = create_speech_generator("gemini", api_key="your-key")
generator = create_default_generator(api_key="your-key")

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
3. Pass card data to `generator.generate()`
4. Update card's Audio field with returned path

```python
import requests
from speech_generator import create_default_generator

# Initialize generator
generator = create_default_generator()

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

5. **"Unsupported TTS provider"**:
   - Currently only "gemini" is supported
   - Check provider name spelling

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
- **Anki Integration**: See [ankiconnect documentation](https://github.com/FooSoft/anki-connect)
- **This Tool**: Open an issue in this repository 