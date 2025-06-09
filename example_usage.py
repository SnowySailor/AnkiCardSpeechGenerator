#!/usr/bin/env python3
"""
Example usage of the SpeechGenerator for Anki cards.
This script demonstrates how to generate audio for Anki cards using Google's Gemini AI.
"""

import os
from speech_generator import SpeechGenerator

def main():
    # Example Anki card data (as returned by ankiconnect API)
    sample_cards = [
        {
            "cardId": 1001,
            "fields": {
                "Front": {"value": "What is the capital of France?"},
                "Back": {"value": "The capital of France is Paris."},
                "Speaker": {"value": "Teacher"},
                "Emotion": {"value": "confident"},
                "Audio": {"value": ""}
            }
        },
        {
            "cardId": 1002,
            "fields": {
                "Question": {"value": "Explain photosynthesis in simple terms."},
                "Answer": {"value": "Photosynthesis is the process by which plants use sunlight, water, and carbon dioxide to make their own food and produce oxygen."},
                "Speaker": {"value": "Dr. Anya"},
                "Emotion": {"value": "enthusiastic"},
                "Audio": {"value": ""}
            }
        },
        {
            "cardId": 1003,
            "fields": {
                "Text": {"value": "Buenos días, ¿cómo está usted?"},
                "Translation": {"value": "Good morning, how are you?"},
                "Speaker": {"value": "Liam"},
                "Emotion": {"value": "friendly"},
                "Audio": {"value": ""}
            }
        }
    ]
    
    # Check if API key is set
    if not os.getenv("GEMINI_API_KEY"):
        print("Please set your GEMINI_API_KEY environment variable")
        print("You can get one from: https://ai.google.dev/")
        return
    
    try:
        # Initialize the speech generator
        print("Initializing SpeechGenerator...")
        generator = SpeechGenerator(
            characters_file="characters.json",
            output_dir="audio_output",
            mp3_bitrate="128k"  # Adjustable compression
        )
        
        # Generate audio for each sample card
        for i, card in enumerate(sample_cards, 1):
            print(f"\nProcessing card {i}/{len(sample_cards)}...")
            print(f"Card ID: {card['cardId']}")
            
            # Extract some info for display
            fields = card['fields']
            speaker = fields.get('Speaker', {}).get('value', 'Unknown')
            emotion = fields.get('Emotion', {}).get('value', 'None')
            
            print(f"Speaker: {speaker}")
            print(f"Emotion: {emotion}")
            
            try:
                # Generate the audio
                audio_path = generator.generate(card)
                print(f"✓ Audio generated successfully: {audio_path}")
                
                # Update the card's Audio field with the path (in a real scenario)
                card['fields']['Audio']['value'] = audio_path
                
            except Exception as e:
                print(f"✗ Error generating audio: {e}")
        
        print(f"\n🎉 Audio generation complete!")
        print(f"Check the 'audio_output' directory for generated MP3 files.")
        
        # Demonstrate compression adjustment
        print(f"\nChanging compression to high quality (192k)...")
        generator.set_compression("192k")
        
        # Generate one more sample with higher quality
        high_quality_card = {
            "cardId": 1004,
            "fields": {
                "Content": {"value": "This is a high-quality audio sample with better compression."},
                "Speaker": {"value": "Narrator"},
                "Emotion": {"value": "clear"},
                "Audio": {"value": ""}
            }
        }
        
        try:
            hq_audio_path = generator.generate(high_quality_card)
            print(f"✓ High-quality audio generated: {hq_audio_path}")
        except Exception as e:
            print(f"✗ Error generating high-quality audio: {e}")
        
        # Demonstrate adding a new character
        print(f"\nAdding a new character 'Storyteller'...")
        generator.add_character(
            name="Storyteller",
            speaker="Schedar",  # One of Gemini's available voices
            prompt_prefix="As a captivating storyteller, narrate with dramatic flair:"
        )
        
        storyteller_card = {
            "cardId": 1005,
            "fields": {
                "Story": {"value": "Once upon a time, in a kingdom far away, there lived a brave knight who sought to find the lost treasure of wisdom."},
                "Speaker": {"value": "Storyteller"},
                "Emotion": {"value": "mysterious"},
                "Audio": {"value": ""}
            }
        }
        
        try:
            story_audio_path = generator.generate(storyteller_card)
            print(f"✓ Storyteller audio generated: {story_audio_path}")
        except Exception as e:
            print(f"✗ Error generating storyteller audio: {e}")
        
    except Exception as e:
        print(f"Error initializing SpeechGenerator: {e}")
        print("\nMake sure you have:")
        print("1. Set the GEMINI_API_KEY environment variable")
        print("2. Installed required dependencies: pip install google-genai pydub")
        print("3. Installed ffmpeg for audio conversion")

if __name__ == "__main__":
    main() 