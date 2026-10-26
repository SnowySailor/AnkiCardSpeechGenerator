import base64
import io
import os
import tempfile

from google import genai
from pydub import AudioSegment

from .base import AudioGenerator

SPEAKER = "Kore"
MODEL = "gemini-3.8-flash-tts"
BITRATE = "128k"
SPEED = 1.0


class GeminiAudioGenerator(AudioGenerator):
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)

    def generate(self, text: str, prompt: str = "") -> bytes:
        # 3.8 TTS speaks the text verbatim; steering goes in speech_metadata.style.
        content = {"type": "text", "text": text}
        if prompt:
            content["annotations"] = [{"type": "speech_metadata", "style": prompt}]

        interaction = self._client.interactions.create(
            model=MODEL,
            input=[{"type": "user_input", "content": [content]}],
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": SPEAKER}]},
        )

        # Unary responses are WAV (RIFF header, 24 kHz mono 16-bit) by default.
        wav_bytes = base64.b64decode(interaction.output_audio.data)
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
