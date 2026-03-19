# Instagram DM Grup Analiz Sistemi

## 📊 Özellikler

- ✅ **Reels/Video tespiti** (carousel içindekiler dahil)
- ✅ **Gönderi ve hikaye analizi**
- ✅ **Haftalık katılım takibi**
- ✅ **Grup yönetimi**

## 🚀 Kurulum

```bash
pip install -r requirements.txt
```

## 💻 Kullanım

1. **Uygulamayı başlat:**
```bash
python app.py
```

2. **Tarayıcıda aç:**
```
http://127.0.0.1:5000
```

3. **Admin paneli:**
```
http://127.0.0.1:5000/admin
Şifre: seho
```

## 🔧 Test

```bash
# Sistem testi
python test_system.py
```

## 📁 Dosyalar

- `app.py` - Ana uygulama
- `models.py` - Veritabanı modelleri
- `templates/` - HTML şablonları
- `requirements.txt` - Bağımlılıklar

## ⚠️ Notlar

- Cookie'leri düzenli güncelleyin
- Rate limit'e dikkat edin
- Engellenmeyi önlemek için yavaş analiz yapın

## 📱 Instagram Cookie Alma

1. Instagram'a giriş yapın
2. F12 > Network > instagram.com isteği
3. Cookie değerlerini kopyalayın
4. Admin panelinden yapıştırın