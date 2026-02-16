import pytest
import json
import sys
import os

# Add src directory to path so tests can import project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def sample_transcript():
    return [
        {"text": "Hello world", "start": 0.0, "duration": 2.5},
        {"text": "This is a test", "start": 2.5, "duration": 3.0},
        {"text": "YouTube transcript", "start": 5.5, "duration": 2.0},
    ]


@pytest.fixture
def sample_transcript_long():
    """A longer transcript for testing edge cases"""
    return [
        {"text": f"Segment {i}", "start": float(i * 5), "duration": 5.0}
        for i in range(100)
    ]


@pytest.fixture
def mock_youtube_html():
    """Mock YouTube page HTML with captions data"""
    captions_data = {
        "playerCaptionsTracklistRenderer": {
            "captionTracks": [
                {
                    "baseUrl": "https://www.youtube.com/api/timedtext?v=test123&lang=en",
                    "name": {"simpleText": "English"},
                    "languageCode": "en",
                    "kind": "asr",
                    "isTranslatable": True,
                },
                {
                    "baseUrl": "https://www.youtube.com/api/timedtext?v=test123&lang=tr",
                    "name": {"simpleText": "Turkish"},
                    "languageCode": "tr",
                    "isTranslatable": True,
                },
            ],
            "translationLanguages": [
                {"languageCode": "en", "languageName": {"simpleText": "English"}},
                {"languageCode": "tr", "languageName": {"simpleText": "Turkish"}},
                {"languageCode": "de", "languageName": {"simpleText": "German"}},
            ],
        }
    }
    return (
        "var ytInitialPlayerResponse = "
        + json.dumps({"captions": captions_data})
        + ";"
    )


@pytest.fixture
def mock_transcript_xml():
    """Mock XML transcript response"""
    return """<?xml version="1.0" encoding="utf-8" ?>
    <transcript>
        <text start="0" dur="2.5">Hello world</text>
        <text start="2.5" dur="3.0">This is a test</text>
        <text start="5.5" dur="2.0">YouTube transcript</text>
    </transcript>"""


@pytest.fixture
def mock_gemini_response():
    """Mock Gemini API response"""
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "Merhaba dünya. Bu bir test. YouTube transkript."
                        }
                    ]
                }
            }
        ]
    }
