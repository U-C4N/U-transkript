# YouTube Transcript Extractor - AI Çeviri Özeti

## Eklenen Yeni Özellikler

### 🤖 AITranscriptTranslator Sınıfı

YouTube videolarından transcript çıkarıp Google Gemini AI ile çeviri yapabilen yeni bir sınıf eklendi.

#### Ana Fonksiyonlar:

1. **`set_model(model_name)`** - Gemini model seçimi
   - Varsayılan: "gemini-2.0-flash-exp"
   - Örnek: `translator.set_model("gemini-2.5-flash")`

2. **`set_api(api_key)`** - API anahtarı ayarlama
   - Google Gemini API anahtarını ayarlar
   - Örnek: `translator.set_api("AIzaSyCYr3thNQ7V_E-8Gg0vPGelz3I5btyWvO0")`

3. **`set_lang(target_language)`** - Hedef dil ayarlama
   - Çeviri yapılacak dili belirler
   - Örnek: `translator.set_lang("Turkish")` veya `translator.set_lang("English")`

4. **`set_type(output_type)`** - Çıktı formatı
   - Desteklenen formatlar: "txt", "json", "xml"
   - Örnek: `translator.set_type("json")`

5. **`örnek_fonksiyon(video_id)`** - Hızlı çeviri
   - Video ID ile otomatik çeviri yapar
   - Örnek: `translator.örnek_fonksiyon("47Psu7KNeAE")`

#### Kullanım Örneği:

```python
from YouTubeTranscriptExtractor import AITranscriptTranslator

# Translator oluştur
translator = AITranscriptTranslator("API_KEY")

# Method chaining ile ayarlar
result = (translator
    .set_model("gemini-2.5-flash")
    .set_api("AIzaSyCYr3thNQ7V_E-8Gg0vPGelz3I5btyWvO0")
    .set_lang("Turkish")
    .set_type("json")
    .translate_transcript("47Psu7KNeAE"))
```

#### Çıktı Formatları:

- **TXT**: Sadece çevrilmiş metin
- **JSON**: Yapılandırılmış veri (orijinal + çeviri + metadata)
- **XML**: XML formatında tam veri

#### Özellikler:

✅ Google Gemini AI entegrasyonu
✅ Method chaining desteği
✅ Çoklu çıktı formatı
✅ Hata yönetimi
✅ Timestamp korunması
✅ Metadata ekleme

## Dosya Değişiklikleri:

- ➕ `ai_translator.py` - Yeni AI çeviri sınıfı
- 🔄 `__init__.py` - Yeni sınıf import edildi
- ➕ `özet.md` - Bu özet dosyası
- ➕ `quick_test.py` - Kısa test ve dosyaya kayıt
- ➕ `requirements.txt` - Gerekli kütüphaneler

## Gereksinimler:

- `requests` kütüphanesi
- Google Gemini API anahtarı
- İnternet bağlantısı

## Test Sonuçları:

✅ **Başarılı Test**: `simple_test.py` - Rick Roll videosu Türkçe'ye çevrildi
🔄 **Final Test**: `final_test.py` - İstenen video ID (47Psu7KNeAE) İngilizce çevirisi

### Örnek Kullanım:

```python
from ai_translator import AITranscriptTranslator

# Hızlı kullanım
translator = AITranscriptTranslator("API_KEY")
result = translator.set_lang("Turkish").translate_transcript("VIDEO_ID")

# Detaylı kullanım
result = (translator
    .set_model("gemini-2.0-flash-exp")
    .set_api("API_KEY")
    .set_lang("English")
    .set_type("json")
    .translate_transcript("47Psu7KNeAE"))
```

## Özellikler Özeti:

🎯 **Ana Fonksiyonlar**: set_model, set_api, set_lang, set_type, translate_transcript
🔗 **Method Chaining**: Zincirleme method çağrıları desteklenir
📊 **Çıktı Formatları**: TXT, JSON, XML
🤖 **AI Model**: Google Gemini 2.0 Flash Exp
🌍 **Çeviri**: Herhangi bir dile çeviri yapabilir 