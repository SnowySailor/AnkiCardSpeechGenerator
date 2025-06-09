import os
import json
import hashlib
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from speech_generator import GeminiSpeechGenerator, create_default_generator


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
                 sentence_field: str = "Sentence",
                 speaker_field: str = "Speaker",
                 emotion_field: str = "Emotion",
                 audio_field: str = "Audio"):
        """
        Initialize the Anki speech processor.
        
        Args:
            speech_generator: Speech generator instance. If None, creates default Gemini generator
            anki_connect_url: URL for AnkiConnect API
            sentence_field: Name of the field containing text to be spoken
            speaker_field: Name of the field containing speaker name
            emotion_field: Name of the field containing emotion
            audio_field: Name of the field to store audio filename
        """
        self.speech_generator = speech_generator or create_default_generator()
        self.anki_connect_url = anki_connect_url
        self.sentence_field = sentence_field
        self.speaker_field = speaker_field
        self.emotion_field = emotion_field
        self.audio_field = audio_field
        
        # Test AnkiConnect connection
        self._test_anki_connect()
    
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
    
    def _generate_audio_hash(self, card: Dict[str, Any]) -> str:
        """
        Generate a hash for the audio based on content, speaker data, and provider.
        
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
        
        # Clean HTML from sentence
        clean_sentence = self.speech_generator._clean_html(sentence)
        
        # Get speaker configuration
        speaker_config = {}
        if speaker_name in self.speech_generator.characters:
            speaker_config = self.speech_generator.characters[speaker_name]
        
        # Create hash input data
        hash_data = {
            'sentence': clean_sentence,
            'speaker_name': speaker_name,
            'speaker_voice': speaker_config.get('speaker', 'Charon'),
            'speaker_prompt': speaker_config.get('promptPrefix', ''),
            'emotion': emotion,
            'provider': self.speech_generator.__class__.__name__,
            'bitrate': self.speech_generator.mp3_bitrate
        }
        
        # Convert to JSON string and hash
        hash_input = json.dumps(hash_data, sort_keys=True)
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()[:16]  # Use first 16 chars
    
    def _extract_hash_from_filename(self, filename: str) -> Optional[str]:
        """
        Extract hash from existing audio filename.
        
        Args:
            filename: Audio filename
            
        Returns:
            Hash string or None if not found
        """
        if not filename:
            return None
        
        # Expected format: "speech_{hash}.mp3"
        try:
            name_without_ext = Path(filename).stem
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
        Check if a card needs audio generation based on hash comparison.
        
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
        
        # Generate new hash
        new_hash = self._generate_audio_hash(card)
        
        # Get existing audio filename
        existing_audio = fields.get(self.audio_field, {}).get('value', '')
        existing_hash = self._extract_hash_from_filename(existing_audio)
        
        # Compare hashes
        needs_generation = existing_hash != new_hash
        
        return needs_generation, new_hash
    
    def _update_card_audio(self, card_id: int, audio_filename: str) -> None:
        """
        Update a card's audio field with the new filename.
        
        Args:
            card_id: Anki card ID
            audio_filename: New audio filename
        """
        self._anki_request("updateNoteFields", {
            "note": {
                "id": card_id,
                "fields": {
                    self.audio_field: audio_filename
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
                
                # Extract card info for display
                sentence = fields.get(self.sentence_field, {}).get('value', '')[:50] + "..."
                speaker = fields.get(self.speaker_field, {}).get('value', 'Unknown')
                emotion = fields.get(self.emotion_field, {}).get('value', 'None')
                
                print(f"  📝 Sentence: {sentence}")
                print(f"  🎭 Speaker: {speaker} ({emotion})")
                print(f"  🔄 Generating audio...")
                
                # Generate audio using the speech generator
                # Modify the card structure to match what the generator expects
                generator_card = {
                    'cardId': card_id,
                    'fields': {
                        'Front': fields.get(self.sentence_field, {}),  # Map sentence to Front for generator
                        'Speaker': fields.get(self.speaker_field, {}),
                        'Emotion': fields.get(self.emotion_field, {}),
                        'Audio': fields.get(self.audio_field, {})
                    }
                }
                
                # Generate audio
                audio_path = self.speech_generator.generate(generator_card)
                
                # Create new filename with hash
                new_filename = f"speech_{new_hash}.mp3"
                new_path = self.speech_generator.output_dir / new_filename
                
                # Rename the generated file to use hash-based name
                if Path(audio_path).exists():
                    Path(audio_path).rename(new_path)
                    audio_path = str(new_path)
                
                # Update card in Anki
                self._update_card_audio(note_id, new_filename)
                
                print(f"  ✅ Generated: {new_filename}")
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
            if sentence:
                hash_val = self._generate_audio_hash(card)
                print(f"  → Would generate: speech_{hash_val}.mp3")
            else:
                print(f"  → No '{self.sentence_field}' field found!") 