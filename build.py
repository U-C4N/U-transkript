#!/usr/bin/env python3
"""
U-Transkript paket oluşturma scripti
"""

import os
import sys
import subprocess
import shutil

def run_command(command, description):
    """Komut çalıştır ve sonucu göster."""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} başarılı!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} başarısız!")
        print(f"Hata: {e.stderr}")
        return False

def clean_build():
    """Önceki build dosyalarını temizle."""
    print("🧹 Önceki build dosyaları temizleniyor...")
    
    dirs_to_remove = ['build', 'dist', 'u_transkript.egg-info']
    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"   Silindi: {dir_name}")
    
    print("✅ Temizlik tamamlandı!")

def check_requirements():
    """Gerekli paketlerin yüklü olup olmadığını kontrol et."""
    print("📋 Gereksinimler kontrol ediliyor...")
    
    required_packages = ['setuptools', 'wheel', 'twine']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"   ✅ {package}")
        except ImportError:
            missing_packages.append(package)
            print(f"   ❌ {package}")
    
    if missing_packages:
        print(f"\n⚠️  Eksik paketler: {', '.join(missing_packages)}")
        print("Yüklemek için: pip install " + " ".join(missing_packages))
        return False
    
    print("✅ Tüm gereksinimler mevcut!")
    return True

def build_package():
    """Paketi oluştur."""
    print("📦 Paket oluşturuluyor...")
    
    # Source distribution oluştur
    if not run_command("python setup.py sdist", "Source distribution oluşturma"):
        return False
    
    # Wheel distribution oluştur
    if not run_command("python setup.py bdist_wheel", "Wheel distribution oluşturma"):
        return False
    
    print("✅ Paket başarıyla oluşturuldu!")
    return True

def check_package():
    """Oluşturulan paketi kontrol et."""
    print("🔍 Paket kontrol ediliyor...")
    
    if not run_command("twine check dist/*", "Paket doğrulama"):
        return False
    
    print("✅ Paket doğrulaması başarılı!")
    return True

def upload_to_test_pypi():
    """Test PyPI'ye yükle."""
    print("🧪 Test PyPI'ye yükleniyor...")
    
    command = "twine upload --repository testpypi dist/*"
    print(f"Komut: {command}")
    print("⚠️  Test PyPI kullanıcı adı ve şifrenizi girmeniz gerekecek.")
    
    return run_command(command, "Test PyPI yükleme")

def upload_to_pypi():
    """PyPI'ye yükle."""
    print("🚀 PyPI'ye yükleniyor...")
    
    command = "twine upload dist/*"
    print(f"Komut: {command}")
    print("⚠️  PyPI kullanıcı adı ve şifrenizi girmeniz gerekecek.")
    
    return run_command(command, "PyPI yükleme")

def main():
    """Ana fonksiyon."""
    print("🎬 U-Transkript Paket Oluşturucu")
    print("=" * 40)
    
    # Gereksinimler kontrolü
    if not check_requirements():
        sys.exit(1)
    
    # Önceki build'leri temizle
    clean_build()
    
    # Paketi oluştur
    if not build_package():
        sys.exit(1)
    
    # Paketi kontrol et
    if not check_package():
        sys.exit(1)
    
    print("\n🎉 Paket başarıyla oluşturuldu!")
    print("\n📁 Oluşturulan dosyalar:")
    
    if os.path.exists("dist"):
        for file in os.listdir("dist"):
            print(f"   📦 dist/{file}")
    
    print("\n🚀 Yükleme seçenekleri:")
    print("1. Test PyPI'ye yükle: python build.py --test")
    print("2. PyPI'ye yükle: python build.py --upload")
    print("3. Lokal test: pip install dist/u-transkript-1.0.0.tar.gz")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            upload_to_test_pypi()
        elif sys.argv[1] == "--upload":
            upload_to_pypi()
        else:
            print("Kullanım: python build.py [--test|--upload]")
    else:
        main() 