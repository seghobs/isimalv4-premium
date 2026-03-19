# Instagram DM Grup Analiz Sistemi

> Instagram grup DM'lerindeki medya paylaşımlarını analiz eden, haftalık katılım takibi yapan ve çoklu hesap yönetimi destekleyen web tabanlı uygulama.

---

## Ne İşe Yarar?

Bu sistem, Instagram DM gruplarınızda paylaşılan **Reels**, **Gönderi** ve **Hikaye** içeriklerini analiz eder. Her üyenin ne paylaştığını, hangi günler aktif olduğunu ve katılım durumunu otomatik olarak takip eder.

**Senaryo:** Bir Instagram grubunda her hafta belirli sayıda paylaşım yapma kuralınız var. Bu sistem kimin paylaşıp paylaşmadığını, kaç gün aktif olduğunu ve eksik günlerini anında gösterir.

---

## Özellikler

- **Medya Tipi Tespiti** — Reels, Gönderi ve Hikaye otomatik sınıflandırma
- **Haftalık Katılım Analizi** — Üyelerin gün bazlı katılım durumu
- **Çoklu Hesap Yönetimi** — Birden fazla Instagram hesabı bağlayın
- **Instagram ile Giriş** — Kullanıcı adı ve şifreyle doğrudan giriş
- **Token Doğrulama** — Hesapların aktif olup olmadığını kontrol edin
- **Tarih Aralığı Analizi** — İstediğiniz tarih aralığını seçin
- **Dark Theme Arayüz** — Modern, göz yormayan tasarım

---

## Kurulum

**Yöntem 1 — Setup Scripti (Önerilen)**

```bash
curl -sL https://raw.githubusercontent.com/seghobs/isimalv4-premium/master/setup.sh | bash
```

Tüm dosyalar `mysite/` klasörüne kopyalanır.

**Yöntem 2 — Manuel**

```bash
git clone https://github.com/seghobs/isimalv4-premium.git
cd isimalv4-premium
pip install -r requirements.txt
python app.py
```

Uygulama `http://localhost:5000` adresinde çalışır.

---

## Kullanım

**1. Hesap Ekleyin**

`/login` sayfasından Instagram kullanıcı adı ve şifrenizle giriş yapın. Token ve cihaz bilgileri otomatik oluşturulur.

**2. Analiz Yapın**

Ana sayfadan grup seçin, tarih aralığı belirleyin ve analizi başlatın.

**3. Sonuçları İnceleyin**

Her üyenin paylaştığı medya türlerini, katılım günlerini ve durumunu görün.

---

## Sayfalar

| Sayfa | Yol | Açıklama |
|-------|-----|----------|
| Ana Sayfa | `/` | Grup ve medya analizi |
| Admin Panel | `/admin` | Hesap yönetimi ve token doğrulama |
| Giriş Sayfası | `/login` | Instagram ile hesap ekleme |

---

## API Endpoint'leri

| Endpoint | Method | Açıklama |
|----------|--------|----------|
| `/api/init` | POST | Analyzer başlat |
| `/api/groups` | GET | Grupları listele |
| `/api/weekly-participation` | POST | Haftalık analiz |
| `/api/login` | POST | Instagram girişi |
| `/api/admin/verify-token` | POST | Token doğrulama |
| `/api/admin/activate-account` | POST | Hesap aktifleştir |
| `/api/admin/get-token` | GET | Hesapları listele |

---

## Teknoloji

- **Backend:** Flask + Flask-SQLAlchemy
- **HTTP Client:** curl_cffi (Android Chrome TLS fingerprint)
- **Veritabanı:** SQLite
- **API:** Instagram Mobile API (`i.instagram.com`)
- **Frontend:** Vanilla JS, Dark Theme CSS

---

## Lisans

MIT
