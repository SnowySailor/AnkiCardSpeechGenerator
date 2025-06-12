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
                 sentence_field: str = "Expression",
                 speaker_field: str = "Speaker",
                 emotion_field: str = "Emotion",
                 audio_field: str = "Audio",
                 keep_local_files: bool = False):
        """
        Initialize the Anki speech processor.
        
        Args:
            speech_generator: Speech generator instance. If None, creates default Gemini generator
            anki_connect_url: URL for AnkiConnect API
            sentence_field: Name of the field containing text to be spoken
            speaker_field: Name of the field containing speaker name
            emotion_field: Name of the field containing emotion
            audio_field: Name of the field to store audio filename
            keep_local_files: Whether to keep local audio files after storing in Anki
        """
        self.speech_generator = speech_generator or create_default_generator()
        self.anki_connect_url = anki_connect_url
        self.sentence_field = sentence_field
        self.speaker_field = speaker_field
        self.emotion_field = emotion_field
        self.audio_field = audio_field
        self.keep_local_files = keep_local_files
        
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
        clean_sentence = self.speech_generator._clean_html(sentence)
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
                emotion_prompt = prompt_prefix[:-1] + f" with {emotion}:"
            else:
                emotion_prompt = f"{prompt_prefix} with {emotion}:"
            
            return f"{emotion_prompt} {text}"
        else:
            # No speaker configuration, just add emotion to default
            return f"Say with {emotion}: {text}"
    
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
                
                # Build text with emotion context if provided
                if emotion and emotion.strip():
                    final_text = self._build_emotion_text(text, speaker_name, emotion)
                else:
                    final_text = text
                
                # Generate audio using the simplified API
                new_filename = f"speech_{new_hash}"
                audio_path = self.speech_generator.generate(
                    speaker_name=speaker_name,
                    text=final_text,
                    output_filename=new_filename
                )
                
                # Store audio file in Anki's media directory
                audio_filename = f"speech_{new_hash}.mp3"
                self._store_audio_in_anki(audio_path, audio_filename)
                
                # Update card in Anki
                self._update_card_audio(note_id, audio_filename)
                
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
            if sentence:
                hash_val = self._generate_audio_hash(card)
                print(f"  → Would generate: [sound:speech_{hash_val}.mp3]")
            else:
                print(f"  → No '{self.sentence_field}' field found!") 