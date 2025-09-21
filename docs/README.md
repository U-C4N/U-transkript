# 🎬 U-Transkript

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/PyPI-u--transkript-orange.svg)](https://pypi.org/project/u-transkript/)
[![AI Powered](https://img.shields.io/badge/AI-Gemini%20Powered-purple.svg)](https://ai.google.dev/)

**Powerful Python library to automatically extract and translate YouTube videos with AI**

U-Transkript is a modern and user-friendly Python package that extracts transcripts (subtitles) from YouTube videos and translates them into your desired language using Google Gemini AI. It offers an excellent solution for education, research, content creation, and much more.

## ✨ Features

🤖 **AI-Powered Translation** - High-quality translations with Google Gemini AI
🌍 **Multi-Language Support** - Ability to translate into 50+ languages
📊 **Flexible Output Formats** - Get results in TXT, JSON, XML formats
🔗 **Method Chaining** - Easy to use with chained function calls
⚡ **Fast and Efficient** - Optimized performance
🛡️ **Secure** - Error handling and secure API calls
📝 **Detailed Documentation** - Comprehensive user guide

## 🚀 Quick Start

### Installation

```bash
pip install u-transkript
```

### Basic Usage

```python
from u_transkript import AITranscriptTranslator

# Create Translator
translator = AITranscriptTranslator("YOUR_GEMINI_API_KEY")

# Translate Video
result = translator.set_lang("English").translate_transcript("dQw4w9WgXcQ")
print(result)
```

### Advanced Usage with Method Chaining

```python
# Set all settings at once
result = (translator
    .set_model("gemini-2.5-flash")
    .set_lang("English") 
    .set_type("json")
    .translate_transcript("VIDEO_ID"))
```

## 📖 Detailed Documentation

### Main Functions

| Function | Description | Example |
|-----------|----------|-------|
| `set_model(model)` | Set the Gemini model | `translator.set_model("gemini-2.5-flash")` |
| `set_api(api_key)` | Set the API key | `translator.set_api("YOUR_API_KEY")` |
| `set_lang(language)` | Set the target language | `translator.set_lang("English")` |
| `set_type(format)` | Set the output format | `translator.set_type("json")` |
| `translate_transcript(video_id)` | Main translation function | `translator.translate_transcript("VIDEO_ID")` |

### Supported Output Formats

#### 📄 TXT Format
```python
translator.set_type("txt")
# Output: "Hello, this is an example translation..."
```

#### 📋 JSON Format
```python
translator.set_type("json")
# Output: Structured JSON data (with metadata)
```

#### 🏷️ XML Format
```python
translator.set_type("xml")
# Output: Full data structure in XML format
```

### Supported Languages

🇹🇷 Turkish • 🇺🇸 English • 🇪🇸 Spanish • 🇫🇷 French • 🇩🇪 German • 🇮🇹 Italian • 🇵🇹 Portuguese • 🇷🇺 Russian • 🇯🇵 Japanese • 🇰🇷 Korean • 🇨🇳 Chinese • 🇸🇦 Arabic

## 💡 Use Cases

### 📰 News Content
```python
# Translating news videos
result = translator.set_lang("English").translate_transcript("NEWS_VIDEO_ID")
```

### 💼 Business Presentations
```python
# Translating technical presentations
result = translator.set_type("json").translate_transcript("PRESENTATION_ID")
```

### 🎬 Content Creation
```python
# Translating YouTube content into different languages
video_ids = ["VIDEO1", "VIDEO2", "VIDEO3"]
for video_id in video_ids:
    result = translator.set_lang("English").translate_transcript(video_id)
    with open(f"{video_id}_en.txt", "w") as f:
        f.write(result)
```

## 🔧 Advanced Features

### Custom Prompt Usage
```python
custom_prompt = """
Please translate this text into {language}:
- Preserve technical terms
- Use natural language
- Maintain context

Text: {text}
"""

result = translator.translate_transcript(
    "VIDEO_ID",
    custom_prompt=custom_prompt
)
```

### Batch Processing
```python
videos = ["VIDEO1", "VIDEO2", "VIDEO3"]
results = []

for video in videos:
    try:
        result = translator.set_lang("English").translate_transcript(video)
        results.append({"video": video, "translation": result})
    except Exception as e:
        results.append({"video": video, "error": str(e)})
```

### Saving to File
```python
# Saving in JSON format
result = translator.set_type("json").translate_transcript("VIDEO_ID")
with open("translation.json", "w", encoding="utf-8") as f:
    f.write(result)
```


## 📊 Performance

| Model | Speed | Quality | Usage |
|-------|-----|--------|----------|
| `gemini-2.5-flash` | ⚡⚡ | ⭐⭐⭐⭐ | Fast, balanced (recommended) |
| `gemini-2.5-pro` | ⚡ | ⭐⭐⭐⭐⭐ | Highest quality |

## 🔍 Troubleshooting

### Common Errors

**API Key Error**
```python
# ❌ Incorrect
translator = AITranscriptTranslator("")

# ✅ Correct  
translator = AITranscriptTranslator("VALID_API_KEY")
```

**Video Not Found**
```python
# Ensure the Video ID is correct
video_id = "dQw4w9WgXcQ"  # 11 characters
```

**Language Error**
```python
# ❌ Incorrect
translator.set_lang("en")

# ✅ Correct
translator.set_lang("English")
```

### Debug Mode
```python
import logging
logging.basicConfig(level=logging.DEBUG)

try:
    result = translator.translate_transcript("VIDEO_ID")
except Exception as e:
    print(f"Error: {e}")
```

## 📈 Roadmap

- [ ] **v1.1.0** - Batch processing support
- [ ] **v1.2.0** - Caching system
- [ ] **v1.3.0** - CLI interface
- [ ] **v1.4.0** - Web interface
- [ ] **v1.5.0** - Support for more AI models

## 🤝 Contributing

We welcome your contributions! 

1. Fork it
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.


## 📞 Contact

- **GitHub**: [u-transkript](https://github.com/U-C4N/u-transkript)
- **PyPI**: [u-transkript](https://pypi.org/project/u-transkript/)
- **Documentation**: [example.md](example.md)
