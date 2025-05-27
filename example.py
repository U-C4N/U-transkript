from youtube_transcript import YouTubeTranscriptApi
from formatters import get_formatter
from exceptions import TranscriptRetrievalError
import json


def example_basic_usage():
    """
    Basic example of getting a transcript.
    """
    print("=== Basic Usage Example ===")

    video_id = "G3iN0vNNNWY"  # Rick Astley - Never Gonna Give You Up

    try:
        # Get transcript in English
        transcript = YouTubeTranscriptApi.get_transcript(video_id,
                                                         languages=['en'])

        print(f"Retrieved transcript with {len(transcript)} entries")
        print("\nFirst 3 entries:")
        for i, entry in enumerate(transcript[:3]):
            print(f"  {i+1}. [{entry['start']:.1f}s] {entry['text']}")

    except TranscriptRetrievalError as e:
        print(f"Error: {e}")


def example_multiple_languages():
    """
    Example of requesting transcript in multiple languages with fallback.
    """
    print("\n=== Multiple Languages Example ===")

    video_id = "dQw4w9WgXcQ"

    try:
        # Try Spanish first, then English as fallback
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id, languages=['es', 'en'])

        print(
            "Successfully retrieved transcript with language preference: es, en"
        )
        print(f"First entry: {transcript[0]['text']}")

    except TranscriptRetrievalError as e:
        print(f"Error: {e}")


def example_list_available_transcripts():
    """
    Example of listing all available transcripts for a video.
    """
    print("\n=== List Available Transcripts Example ===")

    video_id = "dQw4w9WgXcQ"

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        print(f"Available transcripts for video {video_id}:")

        for transcript in transcript_list:
            status = []
            if transcript.is_generated:
                status.append("auto-generated")
            else:
                status.append("manual")

            if transcript.is_translatable:
                status.append("translatable")

            status_str = " (" + ", ".join(status) + ")"
            print(
                f"  - {transcript.language_code}: {transcript.language}{status_str}"
            )

        # Try to get a manually created transcript
        try:
            manual_transcript = transcript_list.find_manually_created_transcript(
                ['en'])
            print(
                f"\nFound manually created transcript: {manual_transcript.language}"
            )
        except:
            print("\nNo manually created transcripts found")

        # Try to get an auto-generated transcript
        try:
            auto_transcript = transcript_list.find_generated_transcript(['en'])
            print(
                f"Found auto-generated transcript: {auto_transcript.language}")
        except:
            print("No auto-generated transcripts found")

    except TranscriptRetrievalError as e:
        print(f"Error: {e}")


def example_translation():
    """
    Example of translating a transcript.
    """
    print("\n=== Translation Example ===")

    video_id = "dQw4w9WgXcQ"

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Find a translatable transcript
        for transcript in transcript_list:
            if transcript.is_translatable:
                print(
                    f"Found translatable transcript: {transcript.language} ({transcript.language_code})"
                )

                # Check available translation languages
                if transcript.translation_languages:
                    print(
                        f"Available translations: {len(transcript.translation_languages)}"
                    )

                    # Try to translate to Spanish
                    try:
                        spanish_transcript = transcript.translate('es')
                        transcript_data = spanish_transcript.fetch()

                        print(f"Successfully translated to Spanish")
                        print(
                            f"First translated entry: {transcript_data[0]['text']}"
                        )
                        break

                    except Exception as e:
                        print(f"Translation failed: {e}")

        else:
            print("No translatable transcripts found")

    except TranscriptRetrievalError as e:
        print(f"Error: {e}")


def example_formatting():
    """
    Example of different output formats.
    """
    print("\n=== Formatting Example ===")

    video_id = "dQw4w9WgXcQ"

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id,
                                                         languages=['en'])

        # Limit to first 3 entries for demonstration
        sample_transcript = transcript[:3]

        # Pretty print format
        print("Pretty Print Format:")
        pretty_formatter = get_formatter('pretty')
        formatted = pretty_formatter.format_transcript(sample_transcript)
        print(formatted)

        # JSON format
        print("\nJSON Format:")
        json_formatter = get_formatter('json')
        formatted = json_formatter.format_transcript(sample_transcript)
        print(formatted)

        # Text format
        print("\nText Format:")
        text_formatter = get_formatter('text')
        formatted = text_formatter.format_transcript(sample_transcript)
        print(formatted)

        # SRT format
        print("\nSRT Format:")
        srt_formatter = get_formatter('srt')
        formatted = srt_formatter.format_transcript(sample_transcript)
        print(formatted)

    except TranscriptRetrievalError as e:
        print(f"Error: {e}")


def example_batch_processing():
    """
    Example of processing multiple videos.
    """
    print("\n=== Batch Processing Example ===")

    video_ids = [
        "dQw4w9WgXcQ",  # Rick Astley - Never Gonna Give You Up
        "9bZkp7q19f0",  # PSY - GANGNAM STYLE
        "kffacxfA7G4",  # Baby Shark Dance
    ]

    results = YouTubeTranscriptApi.get_transcripts(video_ids,
                                                   languages=['en'],
                                                   continue_on_failure=True)

    print(f"Processed {len(results)} videos:")

    for result in results:
        if result['error']:
            print(f"  {result['video_id']}: ERROR - {result['error']}")
        else:
            transcript_length = len(result['transcript'])
            print(
                f"  {result['video_id']}: SUCCESS - {transcript_length} entries"
            )


def example_error_handling():
    """
    Example of proper error handling.
    """
    print("\n=== Error Handling Example ===")

    # Try with an invalid video ID
    invalid_video_id = "invalid_id_123"

    try:
        transcript = YouTubeTranscriptApi.get_transcript(invalid_video_id)
        print("This shouldn't print")
    except TranscriptRetrievalError as e:
        print(f"Caught expected error: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"Caught unexpected error: {type(e).__name__}: {e}")


def main():
    """
    Run all examples.
    """
    print("YouTube Transcript API Examples")
    print("=" * 50)

    example_basic_usage()
    example_multiple_languages()
    example_list_available_transcripts()
    example_translation()
    example_formatting()
    example_batch_processing()
    example_error_handling()

    print("\n" + "=" * 50)
    print("Examples completed!")


if __name__ == "__main__":
    main()
