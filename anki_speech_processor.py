import os
import json
import hashlib
import requests
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from speech_generator import create_default_generator
from bs4 import BeautifulSoup

class AnkiConnectError(Exception):
    """Exception raised for AnkiConnect API errors."""
    pass


class AnkiSpeechProcessor:
    """
    Processes Anki cards to generate speech audio using AnkiConnect API.
    """

    def __init__(self, 
                 speech_generator=None,
                 anki_connect_url: str = "http://localhost:8765",
                 sentence_field: str = "Expression",
                 speaker_field: str = "Speaker",
                 emotion_field: str = "Emotion",
                 audio_field: str = "Audio",
                 regenerate_audio_field: str = "Regenerate Audio",
                 keep_local_files: bool = False,
                 replacements_file: str = "replacements.json"):
        """
        Initialize the Anki speech processor.

        Args:
            speech_generator: Speech generator instance. If None, creates default Gemini generator
            anki_connect_url: URL for AnkiConnect API
            sentence_field: Name of the field containing text to be spoken
            speaker_field: Name of the field containing speaker name
            emotion_field: Name of the field containing emotion
            audio_field: Name of the field to store audio filename
            regenerate_audio_field: Name of the field that triggers regeneration when it has any value
            keep_local_files: Whether to keep local audio files after storing in Anki
            replacements_file: Path to the pronunciations replacements JSON file
        """
        self.speech_generator = speech_generator or create_default_generator()
        self.anki_connect_url = anki_connect_url
        self.sentence_field = sentence_field
        self.speaker_field = speaker_field
        self.emotion_field = emotion_field
        self.audio_field = audio_field
        self.regenerate_audio_field = regenerate_audio_field
        self.keep_local_files = keep_local_files

        # Load replacements
        self.replacements = self._load_replacements(replacements_file)

        # Test AnkiConnect connection
        self._test_anki_connect()

    def _load_replacements(self, replacements_file: str) -> Dict:
        """
        Load pronunciation replacements from JSON file.

        Args:
            replacements_file: Path to the replacements JSON file

        Returns:
            Replacements dictionary or empty dict if file not found
        """
        try:
            with open(replacements_file, 'r', encoding='utf-8') as f:
                replacements = json.load(f)
                print(f"Loaded pronunciation replacements from {replacements_file}")
                return replacements
        except FileNotFoundError:
            print(f"Warning: Replacements file {replacements_file} not found. Proceeding without replacements.")
            return {}
        except json.JSONDecodeError as e:
            print(f"Warning: Invalid JSON in {replacements_file}: {e}. Proceeding without replacements.")
            return {}

    def _parse_source_field(self, source: str) -> Optional[Tuple[str, str, List[str]]]:
        """
        Parse the Source field to extract manga title, volume, and pages.

        Args:
            source: Source field value (e.g., "FUR V1 P12,13" or "ASU V5 P123")

        Returns:
            Tuple of (manga_title, volume, pages_list) or None if invalid format
        """
        if not source:
            return None

        # Match pattern like "FUR V1 P12,13" or "ASU V5 P123"
        pattern = r'^([A-Z]+)\s+V(\d+)\s+P([\d,]+)$'
        match = re.match(pattern, source.strip())

        if not match:
            return None

        manga_title = match.group(1)
        volume = f"V{match.group(2)}"
        pages_str = match.group(3)

        # Split pages by comma and add P prefix
        pages = [f"P{page.strip()}" for page in pages_str.split(',')]

        return manga_title, volume, pages

    def _get_applicable_replacements(self, text: str, source: str) -> List[Tuple[str, str]]:
        """
        Get applicable pronunciation replacements for given text and source.

        Args:
            text: The text content to check
            source: Source field value

        Returns:
            List of (original_word, replacement) tuples that appear in the text
        """
        if not self.replacements:
            return []

        applicable_replacements = []

        # Always check global replacements (top-level "*")
        if "*" in self.replacements:
            global_replacements = self.replacements["*"]
            for original, replacement in global_replacements.items():
                if original in text:
                    applicable_replacements.append((original, replacement))

        # Parse source field
        source_info = self._parse_source_field(source)
        if not source_info:
            return applicable_replacements

        manga_title, volume, pages = source_info

        # Check manga-specific replacements
        if manga_title in self.replacements:
            manga_replacements = self.replacements[manga_title]

            # Check manga-level wildcards
            if "*" in manga_replacements:
                for original, replacement in manga_replacements["*"].items():
                    if original in text and (original, replacement) not in applicable_replacements:
                        applicable_replacements.append((original, replacement))

            # Check volume-specific replacements
            if volume in manga_replacements:
                volume_replacements = manga_replacements[volume]

                # Check volume-level wildcards
                if "*" in volume_replacements:
                    for original, replacement in volume_replacements["*"].items():
                        if original in text and (original, replacement) not in applicable_replacements:
                            applicable_replacements.append((original, replacement))

                # Check page-specific replacements
                for page in pages:
                    if page in volume_replacements:
                        page_replacements = volume_replacements[page]
                        for original, replacement in page_replacements.items():
                            if original in text and (original, replacement) not in applicable_replacements:
                                applicable_replacements.append((original, replacement))

        return applicable_replacements

    def _test_anki_connect(self) -> None:
        """Test if AnkiConnect is available."""
        try:
            response = self._anki_request("version")
            print(f"Connected to AnkiConnect version: {response}")
        except Exception as e:
            raise AnkiConnectError(f"Cannot connect to AnkiConnect: {e}")

    def _anki_request(self, action: str, params: Optional[Dict] = None) -> Any:
        """
        Make a request to AnkiConnect API.

        Args:
            action: AnkiConnect action to perform
            params: Parameters for the action

        Returns:
            Response from AnkiConnect
        """
        if params is None:
            params = {}

        request_data = {
            "action": action,
            "version": 6,
            "params": params
        }

        try:
            response = requests.post(self.anki_connect_url, json=request_data)
            response.raise_for_status()

            result = response.json()
            if result.get("error"):
                raise AnkiConnectError(f"AnkiConnect error: {result['error']}")

            return result.get("result")

        except requests.RequestException as e:
            raise AnkiConnectError(f"Network error: {e}")

    def _get_card_text(self, card: Dict[str, Any]) -> str:
        """
        Extract the text content to be spoken from the Anki card.

        Args:
            card: Anki card data

        Returns:
            Text content to be converted to speech
        """
        fields = card.get('fields', {})
        sentence = fields.get(self.sentence_field, {}).get('value', '')

        # Clean HTML from sentence
        clean_sentence = self._clean_html(sentence)
        return clean_sentence

    def _build_emotion_text(self, text: str, speaker_name: str, emotion: str) -> str:
        """
        Build text with emotion context by modifying the speaker's prompt prefix.

        Args:
            text: The base text to be spoken
            speaker_name: Name of the speaker character
            emotion: Emotion context

        Returns:
            Text with emotion context applied
        """
        if not emotion or not emotion.strip():
            return text

        # Get the base prompt from the speaker configuration
        if speaker_name in self.speech_generator.characters:
            char_config = self.speech_generator.characters[speaker_name]
            prompt_prefix = char_config['promptPrefix']

            # Modify the prompt to include emotion
            # Replace the colon with emotion context
            if prompt_prefix.endswith(':'):
                emotion_prompt = prompt_prefix[:-1] + f"、{emotion}の感情でこれを言いなさい："
            else:
                emotion_prompt = f"{prompt_prefix}、{emotion}の感情でこれを言いなさい："

            return f"{emotion_prompt} {text}"
        else:
            # No speaker configuration, just add emotion to default
            return f"{emotion}の感情でこれを言いなさい： {text}"

    def _build_complete_prompt(self, text: str, speaker_name: str, emotion: str, card: Dict[str, Any]) -> str:
        """
        Build the complete prompt in the desired format with pronunciation replacements:
        Line 1: {character promptPrefix} (if exists)
        Line 2: {emotion}の感情で (if emotion exists)
        Line 3: これを言いなさい： {text} (always included)

        Args:
            text: The base text to be spoken
            speaker_name: Name of the speaker character
            emotion: Emotion context (can be empty)
            card: Anki card data (used to get Source field)

        Returns:
            Complete prompt formatted for speech generation
        """
        prompt_lines = []

        fields = card.get('fields', {})
        source = fields.get('Source', {}).get('value', '')
        replacements = self._get_applicable_replacements(text, source)
        if replacements:
            for original, replacement in replacements:
                text = text.replace(original, f'<phoneme alphabet="yomigana" ph="{replacement}">{original}</phoneme>')

        # Line 1: Character prompt prefix (if exists)
        if speaker_name in self.speech_generator.characters:
            char_config = self.speech_generator.characters[speaker_name]
            prompt_prefix = char_config.get('promptPrefix', '')
            if prompt_prefix and prompt_prefix.strip():
                # Remove trailing colon or punctuation if present
                clean_prefix = prompt_prefix.rstrip(':：。、').strip()
                if clean_prefix:
                    prompt_lines.append(clean_prefix)

        # Line 3: Emotion directive (if emotion exists)
        if emotion and emotion.strip():
            prompt_lines.append(f"、{emotion}の感情で")

        if len(prompt_lines) > 0:
            prompt_lines.append(f"読み上げてください")

        style_text = ''.join(prompt_lines)
        style_text = style_text.rstrip(':：。、').strip()
        return f"{style_text}：\n{text}" if style_text else text

    def _generate_audio_hash(self, card: Dict[str, Any]) -> str:
        """
        Generate a hash for the audio based on content, speaker data, provider, and replacements.

        Args:
            card: Anki card data

        Returns:
            SHA256 hash string
        """
        # Get card fields
        fields = card.get('fields', {})
        sentence = fields.get(self.sentence_field, {}).get('value', '')
        speaker_name = fields.get(self.speaker_field, {}).get('value', 'Narrator')
        emotion = fields.get(self.emotion_field, {}).get('value', '')
        source = fields.get('Source', {}).get('value', '')

        # Clean HTML from sentence
        clean_sentence = self._clean_html(sentence)

        # Get applicable replacements
        replacements = self._get_applicable_replacements(clean_sentence, source)
        if len(replacements) > 0:
            replacements.append(('__replacements_version', 2))

        # Get speaker configuration
        speaker_config = {}
        if speaker_name in self.speech_generator.characters:
            speaker_config = self.speech_generator.characters[speaker_name]

        # Create hash input data
        hash_data = {
            'version': 3,
            'sentence': clean_sentence,
            'speaker_name': speaker_name,
            'speaker_voice': speaker_config.get('speaker', 'Charon'),
            'speaker_prompt': speaker_config.get('promptPrefix', ''),
            'emotion': emotion,
            'source': source,
            'replacements': replacements,  # Include replacements in hash
            'provider': self.speech_generator.__class__.__name__,
            'bitrate': self.speech_generator.mp3_bitrate,
            'speed_multiplier': self.speech_generator.speed_multiplier
        }

        # Convert to JSON string and hash
        hash_input = json.dumps(hash_data, sort_keys=True)
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()[:16]  # Use first 16 chars

    def _extract_hash_from_filename(self, filename: str) -> Optional[str]:
        """
        Extract hash from existing audio filename, handling Anki's [sound:filename.mp3] format.

        Args:
            filename: Audio filename (may be in Anki [sound:filename.mp3] format)

        Returns:
            Hash string or None if not found
        """
        if not filename:
            return None

        # Handle Anki's [sound:filename.mp3] format
        actual_filename = filename
        if filename.startswith('[sound:') and filename.endswith(']'):
            # Extract filename from [sound:filename.mp3] format
            actual_filename = filename[7:-1]  # Remove '[sound:' and ']'

        # Expected format: "speech_{hash}.mp3"
        try:
            name_without_ext = Path(actual_filename).stem
            if name_without_ext.startswith('speech_'):
                return name_without_ext.replace('speech_', '')
        except:
            pass

        return None

    def get_deck_cards(self, deck_name: str) -> List[Dict[str, Any]]:
        """
        Get all cards from a specific deck.

        Args:
            deck_name: Name of the Anki deck

        Returns:
            List of card dictionaries
        """
        # Find cards in the deck
        card_ids = self._anki_request("findCards", {
            "query": f"deck:\"{deck_name}\""
        })

        if not card_ids:
            print(f"No cards found in deck: {deck_name}")
            return []

        # Get detailed card information
        cards_info = self._anki_request("cardsInfo", {
            "cards": card_ids
        })

        print(f"Found {len(cards_info)} cards in deck: {deck_name}")
        return cards_info

    def _needs_audio_generation(self, card: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Check if a card needs audio generation based on hash comparison or regenerate field.

        Args:
            card: Anki card data

        Returns:
            Tuple of (needs_generation: bool, new_hash: str)
        """
        fields = card.get('fields', {})
        sentence = fields.get(self.sentence_field, {}).get('value', '')

        # Skip if no sentence content
        if not sentence or not sentence.strip():
            return False, ""

        # Check if regenerate field has any value
        regenerate_value = fields.get(self.regenerate_audio_field, {}).get('value', '')
        if regenerate_value and regenerate_value.strip():
            print(f"  🔄 Regenerate field has value: '{regenerate_value}' - forcing regeneration")
            # Generate new hash and return True for regeneration
            new_hash = self._generate_audio_hash(card)
            return True, new_hash

        # Generate new hash
        new_hash = self._generate_audio_hash(card)

        # Get existing audio filename
        existing_audio = fields.get(self.audio_field, {}).get('value', '')
        existing_hash = self._extract_hash_from_filename(existing_audio)

        # Compare hashes
        needs_generation = existing_hash != new_hash

        return needs_generation, new_hash

    def _store_audio_in_anki(self, audio_file_path: str, filename: str) -> None:
        """
        Store audio file in Anki's media directory using AnkiConnect.

        Args:
            audio_file_path: Path to the audio file on disk
            filename: Desired filename in Anki's media directory
        """
        import base64

        try:
            # Read the audio file
            with open(audio_file_path, 'rb') as f:
                audio_data = f.read()

            # Encode as base64 for AnkiConnect
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')

            # Store in Anki's media directory
            self._anki_request("storeMediaFile", {
                "filename": filename,
                "data": audio_base64
            })

        except FileNotFoundError:
            raise RuntimeError(f"Audio file not found: {audio_file_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to store audio file in Anki: {e}")

    def _clear_regenerate_field(self, card_id: int) -> None:
        """
        Clear the regenerate audio field after successful processing.

        Args:
            card_id: Anki card ID
        """
        self._anki_request("updateNoteFields", {
            "note": {
                "id": card_id,
                "fields": {
                    self.regenerate_audio_field: ""
                }
            }
        })

    def _update_card_audio(self, card_id: int, audio_filename: str) -> None:
        """
        Update a card's audio field with the new filename in Anki format.

        Args:
            card_id: Anki card ID
            audio_filename: New audio filename (will be formatted as [sound:filename.mp3])
        """
        # Format filename for Anki audio field
        anki_audio_field = f"[sound:{audio_filename}]"

        self._anki_request("updateNoteFields", {
            "note": {
                "id": card_id,
                "fields": {
                    self.audio_field: anki_audio_field
                }
            }
        })

    def process_deck(self, deck_name: str, force_regenerate: bool = False) -> Dict[str, int]:
        """
        Process all cards in a deck to generate speech audio.

        Args:
            deck_name: Name of the Anki deck to process
            force_regenerate: If True, regenerate all audio regardless of hash

        Returns:
            Statistics dictionary with counts
        """
        cards = self.get_deck_cards(deck_name)

        # Sort cards by cardId (creation timestamp) in descending order
        cards.sort(key=lambda card: card.get('cardId', 0), reverse=True)

        stats = {
            'total_cards': len(cards),
            'processed': 0,
            'skipped': 0,
            'errors': 0,
            'no_sentence': 0
        }

        for i, card in enumerate(cards, 1):
            try:
                card_id = card.get('cardId')
                note_id = card.get('note', card_id)  # Use note ID for updates
                fields = card.get('fields', {})

                print(f"\nProcessing card {i}/{len(cards)} (ID: {card_id})")

                # Check if generation is needed
                needs_generation, new_hash = self._needs_audio_generation(card)

                if not needs_generation and not force_regenerate:
                    if not fields.get(self.sentence_field, {}).get('value', '').strip():
                        print("  ⚠️ Skipped: No sentence content")
                        stats['no_sentence'] += 1
                    else:
                        print("  ✓ Skipped: Audio up to date")
                        stats['skipped'] += 1
                    continue

                if not new_hash:
                    print("  ⚠️ Skipped: No sentence content")
                    stats['no_sentence'] += 1
                    continue

                # Extract card info
                text = self._get_card_text(card)
                speaker_name = fields.get(self.speaker_field, {}).get('value', 'Narrator')
                emotion = fields.get(self.emotion_field, {}).get('value', '')

                # Display info
                display_text = text[:50] + "..." if len(text) > 50 else text
                print(f"  📝 Text: {display_text}")
                print(f"  🎭 Speaker: {speaker_name} ({emotion if emotion else 'No emotion'})")
                print(f"  🔄 Generating audio...")

                # Build complete prompt in the new 3-line format
                final_prompt = self._build_complete_prompt(text, speaker_name, emotion, card)

                # Generate audio using the complete prompt API to avoid double prompt processing
                new_filename = f"speech_{new_hash}"
                audio_path = self.speech_generator.generate_with_complete_prompt(
                    speaker_name=speaker_name,
                    complete_prompt=final_prompt,
                    output_filename=new_filename
                )

                # Store audio file in Anki's media directory
                audio_filename = f"speech_{new_hash}.mp3"
                self._store_audio_in_anki(audio_path, audio_filename)

                # Update card in Anki
                self._update_card_audio(note_id, audio_filename)

                # Clear regenerate field if it was set
                regenerate_value = fields.get(self.regenerate_audio_field, {}).get('value', '')
                if regenerate_value and regenerate_value.strip():
                    self._clear_regenerate_field(note_id)

                # Clean up local file if configured to do so
                if not self.keep_local_files:
                    try:
                        os.unlink(audio_path)
                        print(f"  ✅ Generated and stored in Anki: [sound:{audio_filename}]")
                    except OSError:
                        print(f"  ✅ Generated and stored in Anki: [sound:{audio_filename}] (local file cleanup failed)")
                else:
                    print(f"  ✅ Generated and stored in Anki: [sound:{audio_filename}] (local copy kept: {audio_path})")

                stats['processed'] += 1

            except Exception as e:
                print(f"  ❌ Error processing card {card_id}: {e}")
                stats['errors'] += 1
                continue

        return stats

    def print_statistics(self, stats: Dict[str, int]) -> None:
        """
        Print processing statistics.

        Args:
            stats: Statistics dictionary from process_deck
        """
        print(f"\n{'='*50}")
        print(f"PROCESSING COMPLETE")
        print(f"{'='*50}")
        print(f"Total cards:       {stats['total_cards']}")
        print(f"Processed:         {stats['processed']}")
        print(f"Skipped (up-to-date): {stats['skipped']}")
        print(f"Skipped (no content): {stats['no_sentence']}")
        print(f"Errors:            {stats['errors']}")
        print(f"{'='*50}")

    def list_decks(self) -> List[str]:
        """
        Get list of all available decks.

        Returns:
            List of deck names
        """
        return self._anki_request("deckNames")

    def get_card_preview(self, deck_name: str, limit: int = 5) -> None:
        """
        Preview cards from a deck to verify field mapping.

        Args:
            deck_name: Name of the deck
            limit: Number of cards to preview
        """
        cards = self.get_deck_cards(deck_name)

        print(f"\nPreviewing first {min(limit, len(cards))} cards from '{deck_name}':")
        print("-" * 60)

        for i, card in enumerate(cards[:limit]):
            fields = card.get('fields', {})
            print(f"\nCard {i+1} (ID: {card.get('cardId')}):")

            for field_name, field_data in fields.items():
                value = field_data.get('value', '')
                if value:
                    display_value = value[:100] + "..." if len(value) > 100 else value
                    print(f"  {field_name}: {display_value}")

            # Show what would be used for audio generation
            sentence = fields.get(self.sentence_field, {}).get('value', '')
            regenerate_value = fields.get(self.regenerate_audio_field, {}).get('value', '')

            if sentence:
                hash_val = self._generate_audio_hash(card)
                if regenerate_value and regenerate_value.strip():
                    print(f"  → Would regenerate (forced): [sound:speech_{hash_val}.mp3]")
                else:
                    print(f"  → Would generate: [sound:speech_{hash_val}.mp3]")
            else:
                print(f"  → No '{self.sentence_field}' field found!") 

    def _clean_html(self, text: str) -> str:
        soup = BeautifulSoup(text, features="html.parser")
        stripped_text = soup.get_text()
        return stripped_text