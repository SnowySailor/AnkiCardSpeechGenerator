import base64
import io
import os
import random
import tempfile
import time
from typing import Callable

import httpx
from google import genai
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
# Total budget per card across all attempts, so one card can't hold a worker
# indefinitely.
CARD_DEADLINE_S = 30 * 60
MAX_ATTEMPTS = 5
BASE_DELAY_S = 5
RETRYABLE_STATUS = {429, 503}


def _retry_after_s(e: Exception) -> float | None:
    """The wait a 429/503 asked for, if it sent one.

    With the SDK's retries off, we honor it here instead of the SDK sleeping on
    it uncapped, but only within CARD_DEADLINE_S.
    """
    headers = getattr(getattr(e, "response", None), "headers", None) or {}
    try:
        if "retry-after-ms" in headers:
            return float(headers["retry-after-ms"]) / 1000
        if "retry-after" in headers:
            return float(headers["retry-after"])
    except ValueError:
        pass  # e.g. an HTTP-date retry-after; fall back to our own backoff
    return None


def _fmt_wait(seconds: float) -> str:
    return f"{seconds / 60:.0f}m" if seconds >= 120 else f"{seconds:.0f}s"


class GeminiAudioGenerator(AudioGenerator):
    def __init__(self, api_key: str, service_tier: str = SERVICE_TIER):
        self._service_tier = service_tier
        self._client = genai.Client(api_key=api_key)
        # Turn the SDK's own retries off: they run silently and sleep on
        # retry-after-ms uncapped (it once held every worker for over an hour),
        # so all retrying happens in _create, where it's reported and bounded by
        # CARD_DEADLINE_S. HttpRetryOptions can't do this (the client clamps
        # attempts=0 up to 1) and create() won't take a per-call retries=, so
        # clear the interactions client's default instead.
        self._client.interactions.sdk_configuration.retry_config = None

    def generate(
        self,
        text: str,
        prompt: str = "",
        on_status: Callable[[str], None] | None = None,
    ) -> bytes:
        # 3.8 TTS speaks the text verbatim; steering goes in speech_metadata.style.
        content = {"type": "text", "text": text}
        if prompt:
            content["annotations"] = [{"type": "speech_metadata", "style": prompt}]

        interaction = self._create(content, on_status or (lambda _: None))

        # Unary responses are WAV (RIFF header, 24 kHz mono 16-bit) by default.
        wav_bytes = base64.b64decode(interaction.output_audio.data)
        return self._to_mp3(wav_bytes)

    def _create(self, content: dict, on_status: Callable[[str], None]):
        deadline = time.monotonic() + CARD_DEADLINE_S
        for attempt in range(MAX_ATTEMPTS):
            on_status(f"waiting (attempt {attempt + 1}/{MAX_ATTEMPTS})"
                      if attempt else "waiting")
            remaining = deadline - time.monotonic()
            try:
                return self._client.interactions.create(
                    model=MODEL,
                    input=[{"type": "user_input", "content": [content]}],
                    response_format={"type": "audio"},
                    generation_config={"speech_config": [{"voice": SPEAKER}]},
                    service_tier=self._service_tier,
                    timeout=min(REQUEST_TIMEOUT_S, remaining),
                )
            except Exception as e:
                # The SDK doesn't export its status-code or timeout error
                # classes publicly; timeouts wrap the original httpx error.
                status = getattr(e, "status_code", None)
                timed_out = isinstance(e.__cause__, httpx.TimeoutException)
                if (status not in RETRYABLE_STATUS and not timed_out) \
                        or attempt == MAX_ATTEMPTS - 1:
                    raise
                requested = _retry_after_s(e)
                if requested is not None:
                    delay = requested
                else:
                    delay = BASE_DELAY_S * 2**attempt + random.uniform(0, BASE_DELAY_S)
                if time.monotonic() + delay >= deadline:
                    if requested is not None:
                        raise TimeoutError(
                            f"{status}: Gemini asked to wait {_fmt_wait(requested)}, "
                            f"past the {CARD_DEADLINE_S // 60} min budget ({e})"
                        ) from e
                    raise TimeoutError(
                        f"gave up after {CARD_DEADLINE_S // 60} min "
                        f"({attempt + 1} attempts)"
                    ) from e
                on_status(f"{status or 'timeout'}, retrying in {_fmt_wait(delay)} "
                          f"({attempt + 1}/{MAX_ATTEMPTS - 1})")
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
