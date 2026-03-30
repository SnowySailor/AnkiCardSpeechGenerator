from abc import ABC, abstractmethod


class AudioGenerator(ABC):
    @abstractmethod
    def generate(self, text: str) -> bytes:
        """Return MP3 bytes for the given text.

        text may be plain Japanese or contain SSML <phoneme> tags.
        """
