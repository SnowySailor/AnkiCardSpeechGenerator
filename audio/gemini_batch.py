import base64
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Iterator

from google import genai

from .gemini import MODEL, SPEAKER, to_mp3

# Batch bills at 50% of standard like flex, but has its own limits (concurrent
# jobs and enqueued tokens) instead of flex's per-day request cap. Jobs target
# a 24h turnaround and expire if not finished within 48h.
_STATE_PREFIX = "JOB_STATE_"
_DONE = {"SUCCEEDED", "PARTIALLY_SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"}
_OK = {"SUCCEEDED", "PARTIALLY_SUCCEEDED"}


@dataclass
class BatchStatus:
    state: str  # e.g. "RUNNING", without the JOB_STATE_ prefix
    error: str | None = None
    result_file: str | None = None

    @property
    def done(self) -> bool:
        return self.state in _DONE

    @property
    def succeeded(self) -> bool:
        return self.state in _OK


def _request(text: str, prompt: str) -> dict:
    """A generateContent request in REST JSON, as batch input files expect."""
    # 3.8 TTS speaks the text verbatim; steering goes in speechMetadata.style.
    part = {"text": text}
    if prompt:
        part["speechMetadata"] = {"style": prompt}
    return {
        "contents": [{"role": "user", "parts": [part]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": SPEAKER}}
            },
        },
    }


def _get(obj: dict, camel: str, snake: str):
    # The docs don't pin down the output file's field casing; accept both.
    return obj.get(camel, obj.get(snake))


def _decode(line: dict) -> bytes | str:
    """MP3 bytes from one output line, or a description of why there are none."""
    if line.get("error"):
        error = line["error"]
        return error.get("message", str(error)) if isinstance(error, dict) else str(error)
    response = line.get("response") or {}
    for candidate in response.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = _get(part, "inlineData", "inline_data")
            if inline and inline.get("data"):
                mime = _get(inline, "mimeType", "mime_type") or ""
                return to_mp3(base64.b64decode(inline["data"]), mime)
    reasons = [_get(c, "finishReason", "finish_reason") for c in response.get("candidates") or []]
    return f"no audio in response (finish reason: {', '.join(map(str, reasons)) or 'none'})"


class GeminiBatch:
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)

    def submit(self, items: dict[str, tuple[str, str]], display_name: str) -> str:
        """Submit one request per key (text, prompt); returns the job name.

        Uses an uploaded JSONL file rather than inline requests: inline results
        come back inside the job object, which gets large with audio.
        """
        with tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            for key, (text, prompt) in items.items():
                f.write(json.dumps(
                    {"key": key, "request": _request(text, prompt)}, ensure_ascii=False
                ) + "\n")
            path = f.name
        try:
            uploaded = self._client.files.upload(
                file=path, config={"display_name": display_name, "mime_type": "jsonl"}
            )
        finally:
            os.unlink(path)
        job = self._client.batches.create(
            model=MODEL, src=uploaded.name, config={"display_name": display_name}
        )
        return job.name

    def status(self, job_name: str) -> BatchStatus:
        job = self._client.batches.get(name=job_name)
        state = job.state.name if job.state else "UNSPECIFIED"
        return BatchStatus(
            state=state.removeprefix(_STATE_PREFIX),
            error=job.error.message if job.error else None,
            result_file=job.dest.file_name if job.dest else None,
        )

    def results(
        self, status: BatchStatus, keys: list[str]
    ) -> Iterator[tuple[str, bytes | str]]:
        """Yield (key, mp3 bytes or error text) per output line.

        Lines carry the request's key; keys (the submission order) is the
        fallback, since output lines are documented to keep input order.
        """
        data = self._client.files.download(file=status.result_file)
        lines = [l for l in data.decode("utf-8").splitlines() if l.strip()]
        for i, raw in enumerate(lines):
            line = json.loads(raw)
            key = line.get("key") or (keys[i] if i < len(keys) else None)
            if key is None:
                continue
            try:
                yield key, _decode(line)
            except Exception as e:
                yield key, f"could not decode audio: {e}"
