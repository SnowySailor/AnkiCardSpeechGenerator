import time
import os
import json
import wave
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
from google import genai
from google.genai import types
from pydub import AudioSegment
from pydub.utils import which
from bs4 import BeautifulSoup

class SpeechGenerator(ABC):
    """
    Abstract base class for generating speech audio from text.
    """
    
    def __init__(self, 
                 characters_file: str = "characters.json",
                 output_dir: str = "audio_output",
                 mp3_bitrate: str = "128k",
                 speed_multiplier: float = 1.0):
        """
        Initialize the SpeechGenerator base class.
        
        Args:
            characters_file: Path to the JSON file containing character voice definitions
            output_dir: Directory to save generated audio files
            mp3_bitrate: MP3 compression bitrate (e.g., "64k", "128k", "192k", "320k")
            speed_multiplier: Speed multiplier for audio playback (e.g., 1.25 = 125% speed)
        """
        self.characters_file = characters_file
        self.output_dir = Path(output_dir)
        self.mp3_bitrate = mp3_bitrate
        self.speed_multiplier = speed_multiplier
        
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
    
    def _clean_html(self, text: str) -> str:
        soup = BeautifulSoup(text, features="html.parser")
        stripped_text = soup.get_text()
        return stripped_text
    
    def wave_file(self, filename, pcm, channels=1, rate=24000, sample_width=2):
        with wave.open(filename, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(rate)
            wf.writeframes(pcm)

    def _convert_to_mp3(self, wav_data: bytes, output_path: Path) -> None:
        """
        Convert WAV audio data to MP3 and save to file, applying speed adjustment.
        
        Args:
            wav_data: Raw WAV audio data
            output_path: Path where MP3 file should be saved
        """
        # Create temporary WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
            self.wave_file(temp_wav.name, wav_data)
            temp_wav_path = temp_wav.name

        try:
            # Load WAV and apply speed adjustment
            audio = AudioSegment.from_wav(temp_wav_path)
            
            # Apply speed adjustment if speed_multiplier is not 1.0
            if self.speed_multiplier != 1.0:
                # Speed up the audio by changing the sample rate
                # This maintains pitch while changing speed
                audio = audio.speedup(playback_speed=self.speed_multiplier)
            
            # Export to MP3
            audio.export(output_path, format="mp3", bitrate=self.mp3_bitrate)
        finally:
            # Clean up temporary file
            os.unlink(temp_wav_path)
    
    @abstractmethod
    def _generate_audio_data(self, text: str, speaker_name: str) -> bytes:
        """
        Generate audio data from text. Must be implemented by subclasses.
        
        Args:
            text: The complete text to be spoken (including any prompt prefixes)
            speaker_name: Name of the speaker character
            
        Returns:
            WAV audio data as bytes
        """
        pass

    def generate(self, speaker_name: str, text: str, output_filename: Optional[str] = None) -> str:
        """
        Generate speech audio from text using the specified speaker.
        
        Args:
            speaker_name: Name of the speaker character
            text: Text to be converted to speech
            output_filename: Optional custom filename (without extension). If None, generates based on hash.
            
        Returns:
            Path to the generated MP3 audio file
        """
        # Clean HTML from text
        clean_text = self._clean_html(text)
        
        if not clean_text.strip():
            raise ValueError("No text content provided to generate speech")
        
        # Get speaker configuration and build full prompt
        full_prompt = self._build_speech_prompt(clean_text, speaker_name)
        
        # Generate audio data using the specific implementation
        wav_bytes = self._generate_audio_data(full_prompt, speaker_name)
        
        # Generate output filename if not provided
        if output_filename is None:
            # Create a simple hash-based filename including speed
            import hashlib
            hash_input = f"gemini_{speaker_name}_{full_prompt}_{self.speed_multiplier}"
            text_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
            output_filename = f"speech_{text_hash}"
        
        output_path = self.output_dir / f"{output_filename}.mp3"
        # Convert to MP3 and save
        self._convert_to_mp3(wav_bytes, output_path)
        
        return str(output_path)
    
    def generate_with_complete_prompt(self, speaker_name: str, complete_prompt: str, output_filename: Optional[str] = None) -> str:
        """
        Generate speech audio from a complete prompt that bypasses internal prompt building.
        
        Args:
            speaker_name: Name of the speaker character (used for voice selection only)
            complete_prompt: Complete prompt text ready for speech generation
            output_filename: Optional custom filename (without extension). If None, generates based on hash.
            
        Returns:
            Path to the generated MP3 audio file
        """
        # Clean HTML from prompt
        clean_prompt = self._clean_html(complete_prompt)
        
        if not clean_prompt.strip():
            raise ValueError("No prompt content provided to generate speech")
        
        # Generate audio data directly without additional prompt building
        wav_bytes = self._generate_audio_data(clean_prompt, speaker_name)
        
        # Generate output filename if not provided
        if output_filename is None:
            # Create a simple hash-based filename including speed
            import hashlib
            hash_input = f"gemini_{speaker_name}_{clean_prompt}_{self.speed_multiplier}"
            text_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
            output_filename = f"speech_{text_hash}"
        
        output_path = self.output_dir / f"{output_filename}.mp3"
        # Convert to MP3 and save
        self._convert_to_mp3(wav_bytes, output_path)
        
        return str(output_path)
    
    def _build_speech_prompt(self, text: str, speaker_name: str) -> str:
        """
        Build the complete speech prompt including character-specific prefixes.
        
        Args:
            text: The base text to be spoken
            speaker_name: Name of the speaker character
            
        Returns:
            Complete prompt for speech generation
        """
        if speaker_name not in self.characters:
            # Use default if character not found
            return text
        else:
            char_config = self.characters[speaker_name]
            prompt_prefix = char_config['promptPrefix'] if 'promptPrefix' in char_config else ''
            return f"{prompt_prefix} {text}".strip()
    
    def set_compression(self, bitrate: str) -> None:
        """
        Set MP3 compression bitrate.
        
        Args:
            bitrate: MP3 bitrate (e.g., "64k", "128k", "192k", "320k")
        """
        self.mp3_bitrate = bitrate
    
    def set_speed(self, speed_multiplier: float) -> None:
        """
        Set audio speed multiplier.
        
        Args:
            speed_multiplier: Speed multiplier for audio playback (e.g., 1.25 = 125% speed)
        """
        if speed_multiplier <= 0:
            raise ValueError("Speed multiplier must be positive")
        self.speed_multiplier = speed_multiplier
    
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
                 mp3_bitrate: str = "128k",
                 speed_multiplier: float = 1.0):
        """
        Initialize the Gemini speech generator.
        
        Args:
            api_key: Google Gemini API key. If None, will load multiple keys from env.json
            characters_file: Path to the JSON file containing character voice definitions
            output_dir: Directory to save generated audio files
            mp3_bitrate: MP3 compression bitrate (e.g., "64k", "128k", "192k", "320k")
            speed_multiplier: Speed multiplier for audio playback (e.g., 1.25 = 125% speed)
        """
        # Initialize base class first
        super().__init__(characters_file, output_dir, mp3_bitrate, speed_multiplier)
        
        # Load API keys
        if api_key is not None:
            # Single API key provided (backward compatibility)
            api_keys = [api_key]
        else:
            # Load multiple API keys from env.json
            api_keys = self._load_api_keys_from_file()
        
        if not api_keys:
            raise ValueError("At least one API key must be provided either as parameter or in env.json")
        
        # Create clients for each API key
        self.clients = []
        for key in api_keys:
            client = genai.Client(api_key=key)
            self.clients.append(client)
        
        # Round-robin counter
        self._client_index = 0
        
        print(f"Initialized Gemini speech generator with {len(self.clients)} API key(s)")
    
    def _load_api_keys_from_file(self) -> list:
        """Load API keys from env.json file."""
        try:
            with open("env.json", 'r', encoding='utf-8') as f:
                data = json.load(f)
                api_keys = data.get("geminiApiKeys", [])
                if not api_keys:
                    raise ValueError("No API keys found in env.json under 'geminiApiKeys'")
                return api_keys
        except FileNotFoundError:
            raise FileNotFoundError("env.json file not found. Please create it with 'geminiApiKeys' array.")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in env.json: {e}")
    
    def get_next_client(self):
        """Get the next client in round-robin fashion."""
        client = self.clients[self._client_index]
        self._client_index = (self._client_index + 1) % len(self.clients)
        return client
    
    def _generate_audio_data(self, text: str, speaker_name: str) -> bytes:
        """
        Generate audio data using Gemini's TTS API.
        
        Args:
            text: The complete text to be spoken (including prompt prefixes)
            speaker_name: Name of the speaker character
            
        Returns:
            WAV audio data as bytes
        """
        # Get voice configuration
        if speaker_name in self.characters:
            voice_name = self.characters[speaker_name]['speaker']
        else:
            voice_name = 'Kore'  # Default voice

        print(f"    Final prompt: {text}")
        
        # Generate speech using Gemini with retry logic for 429 errors
        max_retries = 3
        for attempt in range(max_retries):
            client = self.get_next_client()
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash-preview-tts",
                    contents=text,
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
                return response.candidates[0].content.parts[0].inline_data.data
                
            except Exception as e:
                # Check if this is a 429 rate limit error
                error_str = str(e).lower()
                is_rate_limit = (
                    "429" in error_str or 
                    "rate limit" in error_str or 
                    "too many requests" in error_str or
                    "quota exceeded" in error_str
                )
                
                if is_rate_limit and attempt < max_retries - 1:
                    print(f"    Rate limit hit (attempt {attempt + 1}/{max_retries}), sleeping for 10 seconds...")
                    time.sleep(10)
                    continue
                else:
                    # If not a rate limit error, or we've exhausted retries, raise the error
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