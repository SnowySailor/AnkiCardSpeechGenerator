from abc import ABC, abstractmethod
from typing import Callable


class AudioGenerator(ABC):
    @abstractmethod
    def generate(
        self,
        text: str,
        prompt: str = "",
        on_status: Callable[[str], None] | None = None,
    ) -> bytes:
        """Return MP3 bytes for the given text.

        text is the plain Japanese sentence to be spoken. prompt is optional
        natural-language steering (e.g. custom pronunciations) that guides
        delivery but is never spoken; empty string means no steering.
        on_status, if given, is called with short progress notes (waiting,
        retrying) from whichever thread runs generate.
        """
