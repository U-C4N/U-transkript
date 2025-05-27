from ai_translator import AITranscriptTranslator

VIDEO_ID = "47Psu7KNeAE"  # Test için video ID
API_KEY = "AIzaSyCYr3thNQ7V_E-8Gg0vPGelz3I5btyWvO0" # API Anahtarın
OUTPUT_FILE = "translation_output.txt" # Çıktı dosyasının adı

try:
    translator = AITranscriptTranslator(API_KEY)
    translation = translator.set_lang("English").set_type("txt").translate_transcript(VIDEO_ID)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(translation)
    print(f"✅ Çeviri tamamlandı ve '{OUTPUT_FILE}' dosyasına kaydedildi.")
except Exception as e:
    print(f"❌ Hata: {e}") 