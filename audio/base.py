from abc import ABC, abstractmethod


class AudioGenerator(ABC):
    @abstractmethod
    def generate(self, text: str, prompt: str = "") -> bytes:
        """Return MP3 bytes for the given text.

        text is the plain Japanese sentence to be spoken. prompt is optional
        natural-language steering (e.g. custom pronunciations) that guides
        delivery but is never spoken; empty string means no steering.
        """
