import time
import os
import json
import wave
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from google import genai
from google.genai import types
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
    def _generate_audio_data(self, text: str, speaker_name: str) -> Union[bytes, _NoAudioResponse]:
        """
        Generate audio data from text. Must be implemented by subclasses.

        Args:
            text: The complete text to be spoken (including any prompt prefixes)
            speaker_name: Name of the speaker character

        Returns:
            WAV audio data as bytes, or NO_AUDIO_RESPONSE if no usable audio
        """
        pass

    def generate_with_complete_prompt(self, speaker_name: str, complete_prompt: str, output_filename: str) -> Union[str, _NoAudioResponse]:
        """
        Generate speech audio from a complete prompt that bypasses internal prompt building.

        Args:
            speaker_name: Name of the speaker character (used for voice selection only)
            complete_prompt: Complete prompt text ready for speech generation
            output_filename: Optional custom filename (without extension). If None, generates based on hash.

        Returns:
            Path to the generated MP3 audio file, or NO_AUDIO_RESPONSE if the
            provider did not return usable audio content.
        """

        if not complete_prompt.strip():
            raise ValueError("No prompt content provided to generate speech")

        # Generate audio data directly without additional prompt building
        wav_bytes = self._generate_audio_data(complete_prompt, speaker_name)
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

        # Batch helpers
        self.batch_display_prefix = "anki-speech-batch"
        self.model_name = "gemini-2.5-pro-preview-tts"

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

    def _build_generate_config(self, voice_name: str) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        )

    def _voice_for_speaker(self, speaker_name: str) -> str:
        if speaker_name in self.characters:
            return self.characters[speaker_name].get('speaker', 'Kore')
        return 'Kore'

    def _extract_audio_from_response(self, response: types.GenerateContentResponse) -> Any:
        if not response or not response.candidates:
            print("    ❌ Gemini response did not include any candidates")
            return NO_AUDIO_RESPONSE

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            print("    ❌ Gemini response candidate did not include any parts")
            return NO_AUDIO_RESPONSE

        for part in candidate.content.parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data and inline_data.data:
                return inline_data.data

        print("    ❌ Gemini response did not include inline audio data")
        return NO_AUDIO_RESPONSE

    def _generate_audio_data(self, text: str, speaker_name: str) -> Union[bytes, _NoAudioResponse]:
        """
        Generate audio data using Gemini's TTS API.

        Args:
            text: The complete text to be spoken (including prompt prefixes)
            speaker_name: Name of the speaker character

        Returns:
            WAV audio data as bytes
        """
        # Get voice configuration
        voice_name = self._voice_for_speaker(speaker_name)

        print(f"    Final prompt: {text}")

        # Generate speech using Gemini with retry logic for 429 errors
        max_retries = 3
        for attempt in range(max_retries):
            client = self.get_next_client()
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=text,
                    config=self._build_generate_config(voice_name),
                )

                # Extract audio data
                return self._extract_audio_from_response(response)

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

    def _wait_for_batch_completion(self, client: genai.Client, job_name: str, poll_interval: float = 15.0) -> types.BatchJob:
        """
        Poll the Gemini API until the specified batch job finishes.
        """
        print(f"  ⏳ Waiting for batch job {job_name} to finish...")
        while True:
            job = client.batches.get(name=job_name)
            state_name = job.state.name if job.state else "UNKNOWN"
            print(f"    • Current state: {state_name}")
            if job.done:
                if state_name == "JOB_STATE_SUCCEEDED":
                    print(f"  ✅ Batch job {job_name} completed successfully")
                    return job
                error_msg = job.error.message if job.error else "unknown error"
                raise RuntimeError(f"Batch job {job_name} finished with state {state_name}: {error_msg}")
            time.sleep(poll_interval)

    def wait_for_pending_batches(self) -> None:
        """
        Check each configured Gemini client for pending batch jobs created by this tool
        and wait until they are completed.
        """
        for idx, client in enumerate(self.clients, start=1):
            try:
                pager = client.batches.list()
            except Exception as exc:
                print(f"⚠️  Unable to list batches for API key #{idx}: {exc}")
                continue

            for job in pager:
                if not job.display_name:
                    continue
                if not job.display_name.startswith(self.batch_display_prefix):
                    continue
                if job.done:
                    continue
                print(f"🔁 API key #{idx}: Pending Gemini batch '{job.display_name}' ({job.name}) detected")
                self._wait_for_batch_completion(client, job.name)

    def do_batch_request(self, batch_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not batch_entries:
            return []

        client = self.get_next_client()
        inlined_requests: List[types.InlinedRequest] = []
        for entry in batch_entries:
            prompt = entry.get("prompt")
            speaker_name = entry.get("speaker_name", "Narrator")
            if not prompt or not prompt.strip():
                raise ValueError("Batch entry missing prompt text")
            voice_name = self._voice_for_speaker(speaker_name)

            inlined_requests.append(
                types.InlinedRequest(
                    contents=prompt,
                    config=self._build_generate_config(voice_name),
                )
            )

        display_name = f"{self.batch_display_prefix}-{int(time.time())}"
        print(f"\n📦 Creating Gemini batch job '{display_name}' with {len(inlined_requests)} requests...")
        batch_job = client.batches.create(
            model=self.model_name,
            src=inlined_requests,
            config=types.CreateBatchJobConfig(display_name=display_name),
        )

        completed_job = self._wait_for_batch_completion(client, batch_job.name)
        dest = completed_job.dest
        if not dest or not dest.inlined_responses:
            raise RuntimeError("Batch job completed but no inline responses were returned")

        inlined_responses = dest.inlined_responses
        if len(inlined_responses) != len(batch_entries):
            print("⚠️  Gemini returned a different number of responses than requested")

        results: List[Dict[str, Any]] = []
        for idx, inline_response in enumerate(inlined_responses):
            if inline_response.error:
                error_message = inline_response.error.message or str(inline_response.error)
                results.append({"error": error_message})
                continue

            response = inline_response.response
            audio_bytes = self._extract_audio_from_response(response)
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