# 🎬 U-Transkript

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/PyPI-u--transkript-orange.svg)](https://pypi.org/project/u-transkript/)
[![AI Powered](https://img.shields.io/badge/AI-Gemini%20Powered-purple.svg)](https://ai.google.dev/)

**YouTube videolarını otomatik olarak çıkarıp AI ile çeviren güçlü Python kütüphanesi**

U-Transkript, YouTube videolarından transcript (altyazı) çıkararak Google Gemini AI ile istediğiniz dile çeviren modern ve kullanıcı dostu bir Python paketidir. Eğitim, araştırma, içerik üretimi ve çok daha fazlası için mükemmel bir çözüm sunar.

## ✨ Özellikler

🤖 **AI Destekli Çeviri** - Google Gemini AI ile yüksek kaliteli çeviriler  
🌍 **Çoklu Dil Desteği** - 50+ dilde çeviri yapabilme  
📊 **Esnek Çıktı Formatları** - TXT, JSON, XML formatlarında sonuç alma  
🔗 **Method Chaining** - Zincirleme fonksiyon çağrıları ile kolay kullanım  
⚡ **Hızlı ve Verimli** - Optimize edilmiş performans  
🛡️ **Güvenli** - Hata yönetimi ve güvenli API çağrıları  
📝 **Detaylı Dokümantasyon** - Kapsamlı kullanım kılavuzu  

## 🚀 Hızlı Başlangıç

### Kurulum

```bash
pip install u-transkript
```

### Temel Kullanım

```python
from u_transkript import AITranscriptTranslator

# Translator oluştur
translator = AITranscriptTranslator("YOUR_GEMINI_API_KEY")

# Video çevir
result = translator.set_lang("Turkish").translate_transcript("dQw4w9WgXcQ")
print(result)
```

### Method Chaining ile Gelişmiş Kullanım

```python
# Tüm ayarları tek seferde yap
result = (translator
    .set_model("gemini-2.5-flash")
    .set_lang("Turkish") 
    .set_type("json")
    .translate_transcript("VIDEO_ID"))
```

## 📖 Detaylı Dokümantasyon

### Ana Fonksiyonlar

| Fonksiyon | Açıklama | Örnek |
|-----------|----------|-------|
| `set_model(model)` | Gemini modelini ayarla | `translator.set_model("gemini-2.5-flash")` |
| `set_api(api_key)` | API anahtarını ayarla | `translator.set_api("YOUR_API_KEY")` |
| `set_lang(language)` | Hedef dili ayarla | `translator.set_lang("Turkish")` |
| `set_type(format)` | Çıktı formatını ayarla | `translator.set_type("json")` |
| `translate_transcript(video_id)` | Ana çeviri fonksiyonu | `translator.translate_transcript("VIDEO_ID")` |

### Desteklenen Çıktı Formatları

#### 📄 TXT Format
```python
translator.set_type("txt")
# Çıktı: "Merhaba, bu bir örnek çeviridir..."
```

#### 📋 JSON Format
```python
translator.set_type("json")
# Çıktı: Yapılandırılmış JSON verisi (metadata ile)
```

#### 🏷️ XML Format
```python
translator.set_type("xml")
# Çıktı: XML formatında tam veri yapısı
```

### Desteklenen Diller

🇹🇷 Türkçe • 🇺🇸 İngilizce • 🇪🇸 İspanyolca • 🇫🇷 Fransızca • 🇩🇪 Almanca • 🇮🇹 İtalyanca • 🇵🇹 Portekizce • 🇷🇺 Rusça • 🇯🇵 Japonca • 🇰🇷 Korece • 🇨🇳 Çince • 🇸🇦 Arapça

## 💡 Kullanım Senaryoları

### 🎓 Eğitim İçeriği
```python
# Eğitim videolarını çevirme
educational_prompt = """
Bu eğitim videosunun transkriptini {language} diline çevirin.
Eğitim terminolojisini koruyun ve anlaşılır olmasına dikkat edin.
İçerik: {text}
"""

result = translator.translate_transcript(
    "EDUCATION_VIDEO_ID",
    custom_prompt=educational_prompt
)
```

### 📰 Haber İçeriği
```python
# Haber videolarını çevirme
result = translator.set_lang("Turkish").translate_transcript("NEWS_VIDEO_ID")
```

### 💼 İş Sunumları
```python
# Teknik sunumları çevirme
result = translator.set_type("json").translate_transcript("PRESENTATION_ID")
```

### 🎬 İçerik Üretimi
```python
# YouTube içeriklerini farklı dillere çevirme
video_ids = ["VIDEO1", "VIDEO2", "VIDEO3"]
for video_id in video_ids:
    result = translator.set_lang("English").translate_transcript(video_id)
    with open(f"{video_id}_en.txt", "w") as f:
        f.write(result)
```

## 🔧 Gelişmiş Özellikler

### Özel Prompt Kullanımı
```python
custom_prompt = """
Lütfen bu metni {language} diline çevirin:
- Teknik terimleri koruyun
- Doğal bir dil kullanın
- Bağlamı koruyun

Metin: {text}
"""

result = translator.translate_transcript(
    "VIDEO_ID",
    custom_prompt=custom_prompt
)
```

### Toplu İşlem
```python
videos = ["VIDEO1", "VIDEO2", "VIDEO3"]
results = []

for video in videos:
    try:
        result = translator.set_lang("Turkish").translate_transcript(video)
        results.append({"video": video, "translation": result})
    except Exception as e:
        results.append({"video": video, "error": str(e)})
```

### Dosyaya Kaydetme
```python
# JSON formatında kaydetme
result = translator.set_type("json").translate_transcript("VIDEO_ID")
with open("ceviri.json", "w", encoding="utf-8") as f:
    f.write(result)
```

## 🛠️ Kurulum ve Gereksinimler

### Sistem Gereksinimleri
- Python 3.7+
- İnternet bağlantısı
- Google Gemini API anahtarı

### Bağımlılıklar
```
requests>=2.25.1
lxml>=4.6.0
```

### Google Gemini API Anahtarı Alma

1. [Google AI Studio](https://makersuite.google.com/app/apikey)'ya gidin
2. Yeni API anahtarı oluşturun
3. Anahtarı güvenli bir yerde saklayın
4. U-Transkript'te kullanın

## 📊 Performans

| Model | Hız | Kalite | Kullanım |
|-------|-----|--------|----------|
| `gemini-2.0-flash-exp` | ⚡⚡⚡ | ⭐⭐⭐ | Hızlı çeviriler |
| `gemini-2.5-flash` | ⚡⚡ | ⭐⭐⭐⭐ | Dengeli performans |
| `gemini-pro` | ⚡ | ⭐⭐⭐⭐⭐ | En yüksek kalite |

## 🔍 Sorun Giderme

### Yaygın Hatalar

**API Anahtarı Hatası**
```python
# ❌ Yanlış
translator = AITranscriptTranslator("")

# ✅ Doğru  
translator = AITranscriptTranslator("VALID_API_KEY")
```

**Video Bulunamadı**
```python
# Video ID'nin doğru olduğundan emin olun
video_id = "dQw4w9WgXcQ"  # 11 karakter
```

**Dil Hatası**
```python
# ❌ Yanlış
translator.set_lang("tr")

# ✅ Doğru
translator.set_lang("Turkish")
```

### Debug Modu
```python
import logging
logging.basicConfig(level=logging.DEBUG)

try:
    result = translator.translate_transcript("VIDEO_ID")
except Exception as e:
    print(f"Hata: {e}")
```

## 📈 Yol Haritası

- [ ] **v1.1.0** - Batch işlem desteği
- [ ] **v1.2.0** - Önbellek sistemi
- [ ] **v1.3.0** - CLI arayüzü
- [ ] **v1.4.0** - Web arayüzü
- [ ] **v1.5.0** - Daha fazla AI model desteği

## 🤝 Katkıda Bulunma

Katkılarınızı memnuniyetle karşılıyoruz! 

1. Fork yapın
2. Feature branch oluşturun (`git checkout -b feature/amazing-feature`)
3. Commit yapın (`git commit -m 'Add amazing feature'`)
4. Push yapın (`git push origin feature/amazing-feature`)
5. Pull Request açın

## 📄 Lisans

Bu proje MIT lisansı altında lisanslanmıştır. Detaylar için [LICENSE](LICENSE) dosyasına bakın.

## 🙏 Teşekkürler

- Google Gemini AI ekibine güçlü AI modelleri için
- YouTube'a transcript API'si için
- Açık kaynak topluluğuna sürekli desteği için

## 📞 İletişim

- **GitHub**: [u-transkript](https://github.com/username/u-transkript)
- **PyPI**: [u-transkript](https://pypi.org/project/u-transkript/)
- **Dokümantasyon**: [example.md](example.md)

## ⭐ Yıldız Verin!

Bu proje işinize yaradıysa, lütfen ⭐ vererek destekleyin!

---

<div align="center">

**U-Transkript ile YouTube videolarını AI gücüyle çevirin! 🚀**

[Kurulum](#kurulum) • [Dokümantasyon](example.md) • [Örnekler](#kullanım-senaryoları) • [Katkıda Bulunma](#katkıda-bulunma)

</div> 