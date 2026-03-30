import io
import os
import tempfile
import wave

from google.cloud import texttospeech
from pydub import AudioSegment

from .base import AudioGenerator

SPEAKER = "Kore"
MODEL = "gemini-2.5-pro-tts"
SAMPLE_RATE = 24000
BITRATE = "128k"
SPEED = 1.0


def _make_client(api_key: str) -> texttospeech.TextToSpeechClient:
    from google.api_core import client_options as client_options_lib

    opts = client_options_lib.ClientOptions(
        api_endpoint="texttospeech.googleapis.com",
    )
    return texttospeech.TextToSpeechClient(client_options=opts)


def _pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class GeminiAudioGenerator(AudioGenerator):
    def __init__(self, api_key: str):
        self._client = _make_client(api_key)

    def generate(self, text: str) -> bytes:
        if "</phoneme>" in text:
            synthesis_input = texttospeech.SynthesisInput(ssml=f"<speak>{text}</speak>")
            voice = texttospeech.VoiceSelectionParams(
                language_code="ja-JP",
                name=f"ja-JP-Chirp3-HD-{SPEAKER}",
            )
        else:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code="ja-JP",
                name=SPEAKER,
                model_name=MODEL,
            )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
        )

        response = self._client.synthesize_speech(
            request=texttospeech.SynthesizeSpeechRequest(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )
        )

        wav_bytes = _pcm_to_wav(response.audio_content)
        return self._to_mp3(wav_bytes)

    def _to_mp3(self, wav_bytes: bytes) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        try:
            audio = AudioSegment.from_wav(tmp_path)
            if SPEED != 1.0:
                audio = audio.speedup(playback_speed=SPEED)
            buf = io.BytesIO()
            audio.export(buf, format="mp3", bitrate=BITRATE)
            return buf.getvalue()
        finally:
            os.unlink(tmp_path)
