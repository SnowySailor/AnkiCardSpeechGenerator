import base64
import requests
from typing import Any

ANKI_URL = "http://localhost:8765"
BATCH_SIZE = 500


class AnkiError(Exception):
    pass


class AnkiClient:
    def __init__(self, url: str = ANKI_URL):
        self.url = url

    def _request(self, action: str, params: dict | None = None) -> Any:
        body = {"action": action, "version": 6, "params": params or {}}
        try:
            resp = requests.post(self.url, json=body)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise AnkiError(f"Network error: {e}")
        data = resp.json()
        if data.get("error"):
            raise AnkiError(f"AnkiConnect: {data['error']}")
        return data["result"]

    def find_cards(self, deck_name: str) -> list[int]:
        return self._request("findCards", {"query": f'deck:"{deck_name}"'})

    def cards_info(self, card_ids: list[int]) -> list[dict]:
        results = []
        for i in range(0, len(card_ids), BATCH_SIZE):
            batch = card_ids[i : i + BATCH_SIZE]
            results.extend(self._request("cardsInfo", {"cards": batch}))
        return results

    def store_media_file(self, filename: str, data: bytes) -> None:
        self._request("storeMediaFile", {
            "filename": filename,
            "data": base64.b64encode(data).decode("ascii"),
        })

    def update_note_field(self, note_id: int, field_name: str, value: str) -> None:
        self._request("updateNoteFields", {
            "note": {"id": note_id, "fields": {field_name: value}}
        })
