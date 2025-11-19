import os
import json
import wave
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from google.cloud import texttospeech
from pydub import AudioSegment
from pydub.utils import which


class _NoAudioResponse:
    def __str__(self) -> str:
        return "No audio response from Gemini"


NO_AUDIO_RESPONSE = _NoAudioResponse()

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

    def wait_for_pending_batches(self) -> None:
        """
        Hook for providers that support batch requests to wait for any queued work.
        Default implementation is a no-op.
        """
        return

    def do_batch_request(self, batch_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Submit a batch request for multiple prompts. Providers that implement this
        should return a list of dictionaries aligned with the input order. Each
        dictionary should contain either an 'audio_data' key with WAV bytes or an
        'error' key describing what went wrong for that entry.
        """
        raise NotImplementedError("Batch requests are not implemented for this provider")

    @abstractmethod
    def _generate_audio_data(
        self,
        style_prompt: Optional[str],
        text: str,
        speaker_name: str
    ) -> Union[bytes, _NoAudioResponse]:
        """
        Generate audio data from text. Must be implemented by subclasses.

        Args:
            style_prompt: Optional style or behavior instructions for the TTS model
            text: The literal text that should be spoken
            speaker_name: Name of the speaker character

        Returns:
            WAV audio data as bytes, or NO_AUDIO_RESPONSE if no usable audio
        """
        pass

    def generate_with_complete_prompt(
        self,
        speaker_name: str,
        style_prompt: Optional[str],
        text: str,
        output_filename: str
    ) -> Union[str, _NoAudioResponse]:
        """
        Generate speech audio when both the style prompt and spoken text are provided.

        Args:
            speaker_name: Name of the speaker character (used for voice selection only)
            style_prompt: Optional natural-language instructions steering delivery/tone
            text: Text that will be vocalized verbatim
            output_filename: Optional custom filename (without extension). If None, generates based on hash.

        Returns:
            Path to the generated MP3 audio file, or NO_AUDIO_RESPONSE if the
            provider did not return usable audio content.
        """

        if not text or not text.strip():
            raise ValueError("No spoken text provided to generate speech")

        # Generate audio data directly without additional prompt building
        wav_bytes = self._generate_audio_data(style_prompt, text, speaker_name)
        if wav_bytes is NO_AUDIO_RESPONSE:
            return NO_AUDIO_RESPONSE

        output_path = self.output_dir / f"{output_filename}.mp3"
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
    Speech generator using Google's Gemini 2.5 Pro TTS model through Cloud Text-to-Speech.
    """

    def __init__(
        self,
        characters_file: str = "characters.json",
        output_dir: str = "audio_output",
        mp3_bitrate: str = "128k",
        speed_multiplier: float = 1.0,
        region: Optional[str] = None
    ):
        """
        Initialize the Gemini speech generator.

        Args:
            characters_file: Path to the JSON file containing character voice definitions
            output_dir: Directory to save generated audio files
            mp3_bitrate: MP3 compression bitrate (e.g., "64k", "128k", "192k", "320k")
            speed_multiplier: Speed multiplier for audio playback (e.g., 1.25 = 125% speed)
            region: Optional region (e.g., "us-central1") to target a specific Text-to-Speech endpoint
        """
        super().__init__(characters_file, output_dir, mp3_bitrate, speed_multiplier)

        client_options = None
        if region:
            api_endpoint = f"{region}-texttospeech.googleapis.com"
            client_options = {"api_endpoint": api_endpoint}

        self.client = texttospeech.TextToSpeechClient(client_options=client_options)
        self.model_name = "gemini-2.5-pro-tts"
        self.sample_rate_hz = 24000

        print("Initialized Gemini speech generator using Cloud Text-to-Speech")

    def _voice_settings_for_speaker(self, speaker_name: str) -> Dict[str, str]:
        char_config = self.characters.get(speaker_name, {})
        voice_name = char_config.get("speaker", "Kore")
        return {"voice_name": voice_name}

    def _build_synthesis_input(self, style_prompt: Optional[str], text: str) -> texttospeech.SynthesisInput:
        if style_prompt and style_prompt.strip():
            return texttospeech.SynthesisInput(text=text, prompt=style_prompt.strip())
        return texttospeech.SynthesisInput(text=text)

    def _generate_audio_data(
        self,
        style_prompt: Optional[str],
        text: str,
        speaker_name: str
    ) -> Union[bytes, _NoAudioResponse]:
        """
        Generate audio data using Gemini's non-preview TTS model.
        """
        voice_settings = self._voice_settings_for_speaker(speaker_name)
        synthesis_input = self._build_synthesis_input(style_prompt, text)

        voice_params = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name=voice_settings["voice_name"],
            model_name=self.model_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.sample_rate_hz,
        )

        if style_prompt:
            print(f"    Style prompt: {style_prompt}")
        print(f"    Spoken text: {text}")

        try:
            response = self.client.synthesize_speech(
                request=texttospeech.SynthesizeSpeechRequest(
                    input=synthesis_input,
                    voice=voice_params,
                    audio_config=audio_config,
                )
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to generate speech with Gemini TTS: {exc}") from exc

        audio_content = getattr(response, "audio_content", None)
        if not audio_content:
            print("    ❌ Gemini TTS response did not include audio content")
            return NO_AUDIO_RESPONSE

        return audio_content

    def wait_for_pending_batches(self) -> None:
        """
        Cloud Text-to-Speech requests are synchronous, so there is nothing to poll.
        """
        return

    def do_batch_request(self, batch_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not batch_entries:
            return []

        results: List[Dict[str, Any]] = []
        for entry in batch_entries:
            text = entry.get("text", "")
            if not text or not text.strip():
                results.append({"error": "Batch entry missing text to speak"})
                continue

            style_prompt = entry.get("style_prompt")
            speaker_name = entry.get("speaker_name", "Narrator")

            try:
                audio_bytes = self._generate_audio_data(style_prompt, text, speaker_name)
            except Exception as exc:
                results.append({"error": str(exc)})
                continue

            if audio_bytes is NO_AUDIO_RESPONSE:
                results.append({"error": NO_AUDIO_RESPONSE})
                continue

            results.append({"audio_data": audio_bytes})

        return results


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