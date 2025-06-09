#!/usr/bin/env python3
"""
Example usage of the SpeechGenerator for Anki cards.
This script demonstrates how to generate audio for Anki cards using Google's Gemini AI.
"""

import os
from speech_generator import GeminiSpeechGenerator, create_speech_generator, create_default_generator

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
        # Demo 1: Initialize using the direct class constructor
        print("=== Demo 1: Direct GeminiSpeechGenerator ===")
        generator = GeminiSpeechGenerator(
            characters_file="characters.json",
            output_dir="audio_output",
            mp3_bitrate="128k"  # Adjustable compression
        )
        
        # Generate audio for the first card
        card = sample_cards[0]
        print(f"Processing card {card['cardId']} with GeminiSpeechGenerator...")
        audio_path = generator.generate(card)
        print(f"✓ Audio generated: {audio_path}")
        
        # Demo 2: Initialize using the factory function
        print(f"\n=== Demo 2: Factory Function ===")
        generator2 = create_speech_generator(
            provider="gemini",
            characters_file="characters.json",
            output_dir="audio_output",
            mp3_bitrate="128k"
        )
        
        # Generate audio for the second card
        card = sample_cards[1]
        print(f"Processing card {card['cardId']} with factory function...")
        audio_path = generator2.generate(card)
        print(f"✓ Audio generated: {audio_path}")
        
        # Demo 3: Initialize using the default generator
        print(f"\n=== Demo 3: Default Generator ===")
        generator3 = create_default_generator(
            characters_file="characters.json",
            output_dir="audio_output",
            mp3_bitrate="128k"
        )
        
        # Generate audio for the third card
        card = sample_cards[2]
        print(f"Processing card {card['cardId']} with default generator...")
        audio_path = generator3.generate(card)
        print(f"✓ Audio generated: {audio_path}")
        
        print(f"\n🎉 Audio generation complete!")
        print(f"Check the 'audio_output' directory for generated MP3 files.")
        
        # Demonstrate compression adjustment
        print(f"\n=== Compression Demo ===")
        print(f"Changing compression to high quality (192k)...")
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
        print(f"\n=== Character Management Demo ===")
        print(f"Adding a new character 'Storyteller'...")
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
        
        # Show available providers
        print(f"\n=== Available Providers ===")
        print("Currently supported TTS providers:")
        print("- gemini (Google Gemini AI)")
        print("- Future providers can be added by extending the SpeechGenerator abstract class")
        
    except Exception as e:
        print(f"Error initializing SpeechGenerator: {e}")
        print("\nMake sure you have:")
        print("1. Set the GEMINI_API_KEY environment variable")
        print("2. Installed required dependencies: pip install google-genai pydub")
        print("3. Installed ffmpeg for audio conversion")

if __name__ == "__main__":
    main() 