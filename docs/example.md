# U-Transkript Kullanım Örnekleri

Bu dosya, `u-transkript` paketinin tüm özelliklerini detaylı örneklerle açıklar.

## 📦 Kurulum

```bash
pip install u-transkript
```

## 🚀 Hızlı Başlangıç

### Basit Çeviri

```python
from u_transkript import AITranscriptTranslator

# API anahtarınızla translator oluşturun
translator = AITranscriptTranslator("YOUR_GEMINI_API_KEY")

# Video ID ile hızlı çeviri
video_id = "dQw4w9WgXcQ"
result = translator.set_lang("Turkish").translate_transcript(video_id)
print(result)
```

## 🔧 Detaylı Kullanım

### 1. AITranscriptTranslator Sınıfı

#### Temel Kurulum
```python
from u_transkript import AITranscriptTranslator

# Translator oluşturma
translator = AITranscriptTranslator(
    api_key="YOUR_GEMINI_API_KEY",
    model="gemini-2.0-flash-exp"  # Varsayılan model
)
```

#### Method Chaining (Zincirleme Çağrılar)
```python
# Tüm ayarları tek seferde yapma
result = (translator
    .set_model("gemini-2.5-flash")
    .set_api("YOUR_API_KEY")
    .set_lang("Turkish")
    .set_type("json")
    .translate_transcript("VIDEO_ID"))
```

### 2. Fonksiyon Detayları

#### `set_model(model_name)`
Kullanılacak Gemini modelini belirler.

```python
# Farklı modeller
translator.set_model("gemini-2.0-flash-exp")    # Hızlı ve verimli
translator.set_model("gemini-2.5-flash")        # Daha gelişmiş
translator.set_model("gemini-pro")              # En güçlü model
```

#### `set_api(api_key)`
Google Gemini API anahtarını ayarlar.

```python
translator.set_api("AIzaSyCYr3thNQ7V_E-8Gg0vPGelz3I5btyWvO0")
```

#### `set_lang(target_language)`
Hedef çeviri dilini belirler.

```python
# Türkçe çeviri
translator.set_lang("Turkish")
translator.set_lang("Türkçe")

# İngilizce çeviri
translator.set_lang("English")

# Diğer diller
translator.set_lang("Spanish")
translator.set_lang("French")
translator.set_lang("German")
translator.set_lang("Japanese")
translator.set_lang("Arabic")
```

#### `set_type(output_type)`
Çıktı formatını belirler.

```python
# Metin formatı (varsayılan)
translator.set_type("txt")

# JSON formatı (metadata ile)
translator.set_type("json")

# XML formatı (yapılandırılmış)
translator.set_type("xml")
```

#### `translate_transcript(video_id, ...)`
Ana çeviri fonksiyonu.

```python
# Basit kullanım
result = translator.translate_transcript("VIDEO_ID")

# Parametreli kullanım
result = translator.translate_transcript(
    video_id="VIDEO_ID",
    target_language="Turkish",  # Geçici dil değişikliği
    output_type="json",         # Geçici format değişikliği
    custom_prompt="Lütfen bu metni resmi bir dille çevir: {text}"
)
```

#### `örnek_fonksiyon(video_id)`
Hızlı çeviri için kısayol fonksiyon.

```python
# Önceden ayarlanmış ayarlarla hızlı çeviri
translator.set_lang("Turkish").set_type("txt")
result = translator.örnek_fonksiyon("VIDEO_ID")
```

### 3. Çıktı Formatları

#### TXT Formatı
```python
translator.set_type("txt")
result = translator.translate_transcript("VIDEO_ID")
# Çıktı: "Merhaba, bu bir örnek çeviridir..."
```

#### JSON Formatı
```python
translator.set_type("json")
result = translator.translate_transcript("VIDEO_ID")
# Çıktı:
{
  "video_id": "VIDEO_ID",
  "target_language": "Turkish",
  "original_transcript": [
    {"text": "Hello", "start": 0.0, "duration": 2.5},
    {"text": "World", "start": 2.5, "duration": 1.8}
  ],
  "translated_text": "Merhaba Dünya",
  "translation_metadata": {
    "model": "gemini-2.0-flash-exp",
    "timestamp": "2024-01-15T10:30:00"
  }
}
```

#### XML Formatı
```python
translator.set_type("xml")
result = translator.translate_transcript("VIDEO_ID")
# Çıktı:
<?xml version="1.0" encoding="UTF-8"?>
<transcript>
    <metadata>
        <video_id>VIDEO_ID</video_id>
        <target_language>Turkish</target_language>
        <model>gemini-2.0-flash-exp</model>
        <timestamp>2024-01-15T10:30:00</timestamp>
    </metadata>
    <original_transcript>
        <entry start="0.0" duration="2.5">
            <text>Hello</text>
        </entry>
    </original_transcript>
    <translated_text>
        <![CDATA[Merhaba Dünya]]>
    </translated_text>
</transcript>
```

### 4. Gelişmiş Örnekler

#### Özel Prompt ile Çeviri
```python
custom_prompt = """
Lütfen aşağıdaki YouTube video transkriptini {language} diline çevirin.
Çeviri yaparken:
- Teknik terimleri koruyun
- Doğal ve akıcı bir dil kullanın
- Bağlamı koruyun

Metin: {text}
"""

result = translator.translate_transcript(
    "VIDEO_ID",
    target_language="Turkish",
    custom_prompt=custom_prompt
)
```

#### Toplu İşlem
```python
video_ids = ["VIDEO_ID_1", "VIDEO_ID_2", "VIDEO_ID_3"]
results = []

for video_id in video_ids:
    try:
        result = translator.set_lang("Turkish").translate_transcript(video_id)
        results.append({"video_id": video_id, "translation": result})
    except Exception as e:
        results.append({"video_id": video_id, "error": str(e)})
```

#### Dosyaya Kaydetme
```python
# TXT dosyasına kaydetme
result = translator.set_type("txt").translate_transcript("VIDEO_ID")
with open("ceviri.txt", "w", encoding="utf-8") as f:
    f.write(result)

# JSON dosyasına kaydetme
result = translator.set_type("json").translate_transcript("VIDEO_ID")
with open("ceviri.json", "w", encoding="utf-8") as f:
    f.write(result)
```

### 5. Hata Yönetimi

```python
try:
    result = translator.translate_transcript("INVALID_VIDEO_ID")
except Exception as e:
    print(f"Hata oluştu: {e}")
    
    # Alternatif video ID dene
    try:
        result = translator.translate_transcript("BACKUP_VIDEO_ID")
    except Exception as e2:
        print(f"Yedek video da başarısız: {e2}")
```

### 6. Performans İpuçları

#### Model Seçimi
```python
# Hızlı çeviri için
translator.set_model("gemini-2.0-flash-exp")

# Kaliteli çeviri için
translator.set_model("gemini-2.5-flash")
```

#### Önbellek Kullanımı
```python
# Aynı video için birden fazla dil
video_id = "VIDEO_ID"

# İlk çeviri (transcript çekilir)
turkish = translator.set_lang("Turkish").translate_transcript(video_id)

# İkinci çeviri (transcript önbellekte)
english = translator.set_lang("English").translate_transcript(video_id)
```

## 🎯 Gerçek Dünya Örnekleri

### Eğitim İçeriği Çevirisi
```python
# Eğitim videosu çevirisi
educational_prompt = """
Bu eğitim videosunun transkriptini {language} diline çevirin.
Eğitim terminolojisini koruyun ve öğrenciler için anlaşılır olmasına dikkat edin.

İçerik: {text}
"""

translator = AITranscriptTranslator("API_KEY")
result = (translator
    .set_model("gemini-2.5-flash")
    .set_lang("Turkish")
    .set_type("json")
    .translate_transcript(
        "EDUCATION_VIDEO_ID",
        custom_prompt=educational_prompt
    ))
```

### Haber İçeriği Çevirisi
```python
# Haber videosu çevirisi
news_prompt = """
Bu haber videosunun transkriptini {language} diline çevirin.
Objektif ve profesyonel bir dil kullanın.
Özel isimleri ve tarihleri koruyun.

Haber içeriği: {text}
"""

result = translator.translate_transcript(
    "NEWS_VIDEO_ID",
    target_language="Turkish",
    output_type="txt",
    custom_prompt=news_prompt
)
```

### Teknik Sunum Çevirisi
```python
# Teknik sunum çevirisi
tech_prompt = """
Bu teknik sunumun transkriptini {language} diline çevirin.
Teknik terimleri İngilizce bırakın ve parantez içinde açıklama ekleyin.
Kod örneklerini olduğu gibi bırakın.

Sunum içeriği: {text}
"""

result = translator.translate_transcript(
    "TECH_PRESENTATION_ID",
    target_language="Turkish",
    custom_prompt=tech_prompt
)
```

## 🔍 Sorun Giderme

### Yaygın Hatalar

1. **API Anahtarı Hatası**
```python
# Yanlış
translator = AITranscriptTranslator("")

# Doğru
translator = AITranscriptTranslator("VALID_API_KEY")
```

2. **Video Bulunamadı**
```python
# Video ID'yi kontrol edin
video_id = "dQw4w9WgXcQ"  # Geçerli YouTube video ID
```

3. **Dil Kodu Hatası**
```python
# Yanlış
translator.set_lang("tr")

# Doğru
translator.set_lang("Turkish")
```

### Debug Modu
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Detaylı hata mesajları için
try:
    result = translator.translate_transcript("VIDEO_ID")
except Exception as e:
    print(f"Detaylı hata: {e}")
    import traceback
    traceback.print_exc()
```

## 📊 Desteklenen Diller

- **Türkçe**: "Turkish", "Türkçe"
- **İngilizce**: "English", "İngilizce"
- **İspanyolca**: "Spanish", "Español"
- **Fransızca**: "French", "Français"
- **Almanca**: "German", "Deutsch"
- **İtalyanca**: "Italian", "Italiano"
- **Portekizce**: "Portuguese", "Português"
- **Rusça**: "Russian", "Русский"
- **Japonca**: "Japanese", "日本語"
- **Korece**: "Korean", "한국어"
- **Çince**: "Chinese", "中文"
- **Arapça**: "Arabic", "العربية"

## 🎉 Sonuç

`u-transkript` paketi ile YouTube videolarını kolayca çevirebilir, farklı formatlarda kaydedebilir ve projelerinizde kullanabilirsiniz. Daha fazla örnek ve güncellemeler için dokümantasyonu takip edin! 