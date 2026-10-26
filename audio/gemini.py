import base64
import io
import os
import random
import tempfile
import time

from google import genai
from google.genai import types
from pydub import AudioSegment

from .base import AudioGenerator

SPEAKER = "Kore"
MODEL = "gemini-3.8-flash-tts"
BITRATE = "128k"
SPEED = 1.0

# Flex bills at 50% of standard but is best-effort: requests can queue for
# minutes or be shed with 429/503, so we raise the timeout and retry ourselves.
SERVICE_TIER = "flex"
REQUEST_TIMEOUT_S = 900
MAX_ATTEMPTS = 5
BASE_DELAY_S = 5
RETRYABLE_STATUS = {429, 503}


class GeminiAudioGenerator(AudioGenerator):
    def __init__(self, api_key: str, service_tier: str = SERVICE_TIER):
        self._service_tier = service_tier
        # The SDK's own retries give up after 30s total, too short for flex
        # shedding, so keep them to the minimum (it clamps 0 up to one quick
        # retry) and rely on the backoff in _create.
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_S * 1000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def generate(self, text: str, prompt: str = "") -> bytes:
        # 3.8 TTS speaks the text verbatim; steering goes in speech_metadata.style.
        content = {"type": "text", "text": text}
        if prompt:
            content["annotations"] = [{"type": "speech_metadata", "style": prompt}]

        interaction = self._create(content)

        # Unary responses are WAV (RIFF header, 24 kHz mono 16-bit) by default.
        wav_bytes = base64.b64decode(interaction.output_audio.data)
        return self._to_mp3(wav_bytes)

    def _create(self, content: dict):
        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._client.interactions.create(
                    model=MODEL,
                    input=[{"type": "user_input", "content": [content]}],
                    response_format={"type": "audio"},
                    generation_config={"speech_config": [{"voice": SPEAKER}]},
                    service_tier=self._service_tier,
                )
            except Exception as e:
                # The SDK doesn't export its status-code error classes publicly.
                status = getattr(e, "status_code", None)
                if status not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS - 1:
                    raise
                delay = BASE_DELAY_S * 2**attempt + random.uniform(0, BASE_DELAY_S)
                print(f"  {status} from Gemini, retrying in {delay:.0f}s "
                      f"({attempt + 1}/{MAX_ATTEMPTS - 1}): {content['text'][:30]}")
                time.sleep(delay)

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
