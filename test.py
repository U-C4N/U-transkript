# -*- coding: utf-8 -*-
import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from youtube_transcript import YouTubeTranscriptApi

# UTF-8 çıktısı için
sys.stdout.reconfigure(encoding='utf-8')

try:
    video_id = "dQw4w9WgXcQ"  # Rick Astley - Never Gonna Give You Up

    print(f"Testing u-transkript library with video ID: {video_id}")
    print("=" * 50)

    # List available transcripts
    print("1. Listing available transcripts...")
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    print(f"Available languages: {transcript_list.get_languages()}")
    print(f"Generated transcripts: {transcript_list.get_generated_languages()}")
    print(f"Manual transcripts: {transcript_list.get_manually_created_languages()}")
    print()

    # Try to get English transcript
    print("2. Fetching English transcript...")
    try:
        transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        print(f"Transcript found: {len(transcript_data)} segments")
        print("First 5 segments:")
        for i, segment in enumerate(transcript_data[:5]):
            print(f"  {i+1}. [{segment['start']:.1f}s - {segment['start'] + segment['duration']:.1f}s] {segment['text']}")
    except Exception as e:
        print(f"Failed to get English transcript: {e}")

    print()

    # Try with any available language
    print("3. Trying with any available language...")
    try:
        transcript_data = YouTubeTranscriptApi.get_transcript(video_id)
        print(f"Transcript found: {len(transcript_data)} segments")
        if transcript_data:
            print("First 3 segments:")
            for i, segment in enumerate(transcript_data[:3]):
                print(f"  {i+1}. [{segment['start']:.1f}s] {segment['text']}")
    except Exception as e:
        print(f"Failed to get any transcript: {e}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()