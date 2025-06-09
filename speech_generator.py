import os
import json
import base64
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
from google import genai
from google.genai import types
from pydub import AudioSegment
from pydub.utils import which


class SpeechGenerator(ABC):
    """
    Abstract base class for generating speech audio from Anki cards.
    """
    
    def __init__(self, 
                 characters_file: str = "characters.json",
                 output_dir: str = "audio_output",
                 mp3_bitrate: str = "128k"):
        """
        Initialize the SpeechGenerator base class.
        
        Args:
            characters_file: Path to the JSON file containing character voice definitions
            output_dir: Directory to save generated audio files
            mp3_bitrate: MP3 compression bitrate (e.g., "64k", "128k", "192k", "320k")
        """
        self.characters_file = characters_file
        self.output_dir = Path(output_dir)
        self.mp3_bitrate = mp3_bitrate
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load character definitions
        self.characters = self._load_characters()
        
        # Check if ffmpeg is available for audio conversion
        if not which("ffmpeg"):
            raise RuntimeError("ffmpeg is required for MP3 conversion. Please install it first.")
    
    def _load_characters(self) -> Dict[str, Any]:
        """Load character definitions from JSON file."""
        try:
            with open(self.characters_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Characters file '{self.characters_file}' not found")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in characters file: {e}")
    
    def _get_audio_content(self, card: Dict[str, Any]) -> str:
        """
        Extract the text content to be spoken from the Anki card.
        
        Args:
            card: Anki card data as returned by ankiconnect API
            
        Returns:
            Text content to be converted to speech
        """
        # Look for common text fields in Anki cards
        fields = card.get('fields', {})
        
        # Try common field names for content
        content_fields = ['Front', 'Back', 'Question', 'Answer', 'Text', 'Content']
        
        for field_name in content_fields:
            if field_name in fields and fields[field_name].get('value'):
                return fields[field_name]['value']
        
        # If no standard fields found, concatenate all non-empty fields except Audio
        content_parts = []
        for field_name, field_data in fields.items():
            if field_name not in ['Audio', 'Speaker', 'Emotion'] and field_data.get('value'):
                content_parts.append(field_data['value'])
        
        return ' '.join(content_parts) if content_parts else "No content found"
    
    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        import re
        # Simple HTML tag removal
        clean_text = re.sub(r'<[^>]+>', '', text)
        # Clean up extra whitespace
        clean_text = ' '.join(clean_text.split())
        return clean_text
    
    def _convert_to_mp3(self, wav_data: bytes, output_path: Path) -> None:
        """
        Convert WAV audio data to MP3 and save to file.
        
        Args:
            wav_data: Raw WAV audio data
            output_path: Path where MP3 file should be saved
        """
        # Create temporary WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
            temp_wav.write(wav_data)
            temp_wav_path = temp_wav.name
        
        try:
            # Load WAV and convert to MP3
            audio = AudioSegment.from_wav(temp_wav_path)
            audio.export(output_path, format="mp3", bitrate=self.mp3_bitrate)
        finally:
            # Clean up temporary file
            os.unlink(temp_wav_path)
    
    @abstractmethod
    def _generate_audio_data(self, text: str, speaker_name: str, emotion: str = "") -> bytes:
        """
        Generate audio data from text. Must be implemented by subclasses.
        
        Args:
            text: The text to be spoken
            speaker_name: Name of the speaker character
            emotion: Emotion context for the speech
            
        Returns:
            WAV audio data as bytes
        """
        pass
    
    def generate(self, card: Dict[str, Any]) -> str:
        """
        Generate speech audio for an Anki card.
        
        Args:
            card: Anki card data as returned by ankiconnect API
            
        Returns:
            Path to the generated MP3 audio file
        """
        # Extract card information
        fields = card.get('fields', {})
        speaker_name = fields.get('Speaker', {}).get('value', 'Narrator')
        emotion = fields.get('Emotion', {}).get('value', '')
        
        # Get text content to speak
        text_content = self._get_audio_content(card)
        clean_text = self._clean_html(text_content)
        
        if not clean_text.strip():
            raise ValueError("No text content found in card to generate speech")
        
        # Generate audio data using the specific implementation
        wav_bytes = self._generate_audio_data(clean_text, speaker_name, emotion)
        
        # Generate output filename
        card_id = card.get('cardId', 'unknown')
        output_filename = f"card_{card_id}_{speaker_name.replace(' ', '_')}.mp3"
        output_path = self.output_dir / output_filename
        
        # Convert to MP3 and save
        self._convert_to_mp3(wav_bytes, output_path)
        
        return str(output_path)
    
    def set_compression(self, bitrate: str) -> None:
        """
        Set MP3 compression bitrate.
        
        Args:
            bitrate: MP3 bitrate (e.g., "64k", "128k", "192k", "320k")
        """
        self.mp3_bitrate = bitrate
    
    def add_character(self, name: str, speaker: str, prompt_prefix: str) -> None:
        """
        Add a new character configuration.
        
        Args:
            name: Character name
            speaker: Voice name to use (provider-specific)
            prompt_prefix: Prompt prefix for this character
        """
        self.characters[name] = {
            "speaker": speaker,
            "promptPrefix": prompt_prefix
        }
        
        # Save updated characters to file
        with open(self.characters_file, 'w', encoding='utf-8') as f:
            json.dump(self.characters, f, indent=2, ensure_ascii=False)


class GeminiSpeechGenerator(SpeechGenerator):
    """
    Speech generator using Google's Gemini AI text-to-speech.
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None,
                 characters_file: str = "characters.json",
                 output_dir: str = "audio_output",
                 mp3_bitrate: str = "128k"):
        """
        Initialize the Gemini speech generator.
        
        Args:
            api_key: Google Gemini API key. If None, will try to get from GEMINI_API_KEY env var
            characters_file: Path to the JSON file containing character voice definitions
            output_dir: Directory to save generated audio files
            mp3_bitrate: MP3 compression bitrate (e.g., "64k", "128k", "192k", "320k")
        """
        # Initialize base class first
        super().__init__(characters_file, output_dir, mp3_bitrate)
        
        # Set up Gemini-specific configuration
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("API key must be provided either as parameter or GEMINI_API_KEY environment variable")
        
        # Initialize Gemini client
        self.client = genai.Client(api_key=self.api_key)
    
    def _generate_speech_content(self, text: str, speaker_name: str, emotion: str = "") -> str:
        """
        Generate the full prompt for speech generation.
        
        Args:
            text: The text to be spoken
            speaker_name: Name of the speaker character
            emotion: Emotion context for the speech
            
        Returns:
            Complete prompt for speech generation
        """
        if speaker_name not in self.characters:
            # Use default if character not found
            prompt_prefix = f"Say"
            if emotion:
                prompt_prefix += f" {emotion}:"
            else:
                prompt_prefix += ":"
        else:
            char_config = self.characters[speaker_name]
            prompt_prefix = char_config['promptPrefix']
            if emotion:
                prompt_prefix = prompt_prefix.replace(":", f" with {emotion}:")
        
        return f"{prompt_prefix} {text}"
    
    def _generate_audio_data(self, text: str, speaker_name: str, emotion: str = "") -> bytes:
        """
        Generate audio data using Gemini's TTS API.
        
        Args:
            text: The text to be spoken
            speaker_name: Name of the speaker character
            emotion: Emotion context for the speech
            
        Returns:
            WAV audio data as bytes
        """
        # Generate speech prompt
        speech_prompt = self._generate_speech_content(text, speaker_name, emotion)
        
        # Get voice configuration
        if speaker_name in self.characters:
            voice_name = self.characters[speaker_name]['speaker']
        else:
            voice_name = 'Charon'  # Default voice
        
        # Generate speech using Gemini
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=speech_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice_name,
                            )
                        )
                    ),
                )
            )
            
            # Extract audio data
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            wav_bytes = base64.b64decode(audio_data)
            
            return wav_bytes
            
        except Exception as e:
            raise RuntimeError(f"Failed to generate speech with Gemini: {e}")


# Factory function to create the default speech generator
def create_speech_generator(provider: str = "gemini", **kwargs) -> SpeechGenerator:
    """
    Factory function to create a speech generator.
    
    Args:
        provider: The TTS provider to use ("gemini" is currently the only option)
        **kwargs: Additional arguments to pass to the generator constructor
        
    Returns:
        A SpeechGenerator instance
    """
    if provider.lower() == "gemini":
        return GeminiSpeechGenerator(**kwargs)
    else:
        raise ValueError(f"Unsupported TTS provider: {provider}. Available: 'gemini'")


# For backward compatibility and convenience, make Gemini the default
def create_default_generator(**kwargs) -> GeminiSpeechGenerator:
    """
    Create the default speech generator (Gemini).
    
    Args:
        **kwargs: Arguments to pass to the GeminiSpeechGenerator constructor
        
    Returns:
        A GeminiSpeechGenerator instance
    """
    return GeminiSpeechGenerator(**kwargs) 