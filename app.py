from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from curl_cffi import requests
import json
import re
from datetime import datetime, timedelta, timezone, date
import secrets
import os
import pytz
from models import db, Cookie, BearerToken, Group, User, GroupUser, Message, MediaShare, WeeklyActivity, SystemLog
import uuid
import random

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Database configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "instagram_analyzer.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)
migrate = Migrate(app, db)

# Admin password
ADMIN_PASSWORD = "seho"

class MediaShareAnalyzer:
    """
    Gruplardaki medya paylaşımlarını analiz eden sınıf - Bearer Token entegrasyonlu.
    Instagram Mobile API kullanır.
    """
    
    def __init__(self, account_id=None):
        # chrome_android impersonate: TLS fingerprint'i gerçek Android cihaz gibi gösterir
        # Instagram mobil API'ye uygun, tarayıcı değil mobil uygulama gibi davranır
        self.session = requests.Session(impersonate="chrome_android")
        self.base_url = "https://i.instagram.com"
        self.api_url = f"{self.base_url}/api/v1"
        self.username = None
        self.bearer_token = None
        self.user_id = None
        self.android_id = None
        self.user_agent = None
        self.device_id = None
        self.account_id = account_id
        self.load_token_from_db(account_id)
        self._setup_headers()
        self._fetch_and_update_username()
    
    def _fetch_and_update_username(self):
        """Header'lar ayarlandıktan sonra kullanıcı adını çeker ve DB'yi günceller"""
        try:
            self.get_username()
            
            # İlgili token kaydını bul
            if self.account_id:
                token_record = BearerToken.query.get(self.account_id)
            else:
                token_record = BearerToken.query.filter_by(is_active=True).first()
                if not token_record:
                    token_record = BearerToken.query.order_by(BearerToken.updated_at.desc()).first()
            
            if token_record and self.username and self.username != 'instagram_user':
                if token_record.username != self.username:
                    token_record.username = self.username
                    db.session.commit()
                if not token_record.user_id and self.user_id:
                    token_record.user_id = self.user_id
                    db.session.commit()
        except Exception as e:
            print(f"Username güncelleme hatası: {e}")
    
    def load_token_from_db(self, account_id=None):
        """Bearer Token'ı veritabanından yükler - Aktif hesabı yükler"""
        try:
            if account_id:
                token_record = BearerToken.query.get(account_id)
            else:
                # Aktif hesabı yükle, yoksa en son ekleneni al
                token_record = BearerToken.query.filter_by(is_active=True).first()
                if not token_record:
                    token_record = BearerToken.query.order_by(BearerToken.updated_at.desc()).first()
            
            if not token_record:
                error_msg = "Bearer Token bulunamadı.\nLütfen admin panelinden token değerini girin."
                print(f"❌ {error_msg}")
                raise ValueError(error_msg)
            
            self.bearer_token = token_record.token
            self.user_id = token_record.user_id
            self.android_id = token_record.android_id
            self.user_agent = token_record.user_agent
            self.device_id = token_record.device_id
            
            # Eğer device_id yoksa android_id'den oluştur
            if not self.device_id and self.android_id:
                android_clean = self.android_id.replace('android-', '')
                if len(android_clean) >= 32:
                    self.device_id = f'{android_clean[:8]}-{android_clean[8:12]}-{android_clean[12:16]}-{android_clean[16:20]}-{android_clean[20:32]}'
                else:
                    self.device_id = android_clean
            
            label = token_record.account_label or token_record.username or 'Bilinmeyen'
            print(f"✓ Bearer Token yüklendi: [{label}]")
            
            # Log kaydı
            log = SystemLog(
                action='token_loaded',
                details=f'Bearer token loaded: {label}',
                status='success'
            )
            db.session.add(log)
            db.session.commit()
            
        except Exception as e:
            log = SystemLog(
                action='token_load_failed',
                details=str(e),
                status='error',
                error_message=str(e)
            )
            db.session.add(log)
            db.session.commit()
            raise Exception(f"Token yükleme hatası: {str(e)}")
    
    def get_username(self):
        """
        Kullanıcı adını API'den alır
        """
        try:
            # Önce current user endpoint'ini dene
            url = f"{self.api_url}/accounts/current_user/?edit=true"
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                user_data = data.get('user', {})
                self.username = user_data.get('username', 'instagram_user')
                if not self.user_id:
                    self.user_id = str(user_data.get('pk', ''))
                return
            
            # Fallback: user_id ile dene
            if self.user_id:
                url = f"{self.api_url}/users/{self.user_id}/info/"
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    self.username = data.get('user', {}).get('username', self.user_id)
                    return
            
            self.username = self.user_id or 'instagram_user'
        except Exception as e:
            self.username = self.user_id or 'instagram_user'
            print(f"Username fetch error: {e}")
    
    def _extract_user_id_from_token(self):
        """Bearer token'dan user_id bilgisini çıkarır"""
        try:
            if self.bearer_token:
                import base64
                # Bearer token base64 encoded JSON içerir
                # Padding ekle
                token_data = self.bearer_token
                padding = 4 - len(token_data) % 4
                if padding != 4:
                    token_data += '=' * padding
                decoded = base64.b64decode(token_data).decode('utf-8')
                token_json = json.loads(decoded)
                user_id = token_json.get('ds_user_id', '')
                if user_id:
                    self.user_id = user_id
                    print(f"✅ Token'dan user_id çıkarıldı: {user_id}")
                    return user_id
        except Exception as e:
            print(f"⚠️ Token'dan user_id çıkarılamadı: {e}")
        return None
    
    def _setup_headers(self):
        """
        Instagram Mobile API HTTP başlıklarını ayarlar
        Gerçek Instagram uygulamasının gönderdiği header'larla eşleştirildi
        dm3.txt'teki başarılı istek referans alınarak hazırlandı
        """
        # Token'dan user_id çıkar
        token_user_id = self._extract_user_id_from_token() or self.user_id or ''
        
        # User Agent: DB'den gelen değer veya varsayılan
        ua = self.user_agent or 'Instagram 415.0.0.36.76 Android (28/9; 240dpi; 720x1280; Asus; ASUS_I003DD; ASUS_I003DD; intel; tr_TR; 874816591)'
        
        # Android ID değerini hazırla
        android_id_raw = self.android_id or ''
        android_id_with_prefix = android_id_raw
        if android_id_raw and not android_id_raw.startswith('android-'):
            android_id_with_prefix = f'android-{android_id_raw}'
        android_id_without_prefix = android_id_raw.replace('android-', '') if android_id_raw else ''
        
        headers = {
            # Temel kimlik
            'User-Agent': ua,
            'Authorization': f'Bearer IGT:2:{self.bearer_token}',
            'Accept-Language': 'tr-TR, en-US',
            'Priority': 'u=3',
            
            # Instagram App bilgileri
            'X-IG-App-ID': '567067343352427',
            'X-IG-Capabilities': '3brTv10=',
            'X-IG-Connection-Type': 'WIFI',
            'X-IG-App-Locale': 'tr_TR',
            'X-IG-Device-Locale': 'tr_TR',
            'X-IG-Mapped-Locale': 'tr_TR',
            'X-IG-Timezone-Offset': '10800',
            'X-IG-Is-Foldable': 'false',
            
            # Facebook/Meta bilgileri
            'X-FB-Client-IP': 'True',
            'X-FB-Server-Cluster': 'True',
            'X-FB-Connection-Type': 'WIFI',
            'X-FB-HTTP-Engine': 'Tigon/MNS/TCP',
            
            # Bandwidth (dm3.txt'ten)
            'X-IG-Bandwidth-Speed-KBPS': '-1.000',
            'X-IG-Bandwidth-TotalBytes-B': '0',
            'X-IG-Bandwidth-TotalTime-MS': '0',
            
            # Bloks bilgileri (dm3.txt'ten)
            'X-Bloks-Is-Layout-RTL': 'false',
            'X-Bloks-Version-ID': 'cde38ed121b450d263742dc90efbd3d862247135473330574c1e5f63a6afd97d',
            'X-Bloks-Is-Panorama-Enabled': 'true',
            
            # Encoding (gzip/deflate - Python requests zstd desteklemiyor)
            'Accept-Encoding': 'gzip, deflate',
            
            # Retry bilgisi
            'X-Tigon-Is-Retry': 'False',
        }
        
        # User ID varsa ilgili header'ları ekle
        if token_user_id:
            headers['IG-Intended-User-ID'] = str(token_user_id)
            headers['IG-U-DS-User-ID'] = str(token_user_id)
        
        # Device ID'leri ekle - Her hesaba özel device_id kullan
        if android_id_with_prefix:
            headers['X-IG-Android-ID'] = android_id_with_prefix
        if self.device_id:
            headers['X-IG-Device-ID'] = self.device_id
        elif android_id_without_prefix:
            # UUID formatında device ID oluştur
            did = android_id_without_prefix
            if len(did) >= 32:
                headers['X-IG-Device-ID'] = f'{did[:8]}-{did[8:12]}-{did[12:16]}-{did[16:20]}-{did[20:32]}'
            else:
                headers['X-IG-Device-ID'] = did
        
        self.session.headers.update(headers)
        print(f"[*] HTTP Header'lar ayarlandi (User-ID: {token_user_id or 'Yok'})")
    
    def _update_headers_from_response(self, response):
        """API response'undaki ig-set-* header'larini session'a uygular"""
        try:
            resp_headers = response.headers
            
            new_rur = resp_headers.get('ig-set-ig-u-rur', '').strip()
            if new_rur:
                self.session.headers['IG-U-RUR'] = new_rur
            
            new_mid = resp_headers.get('ig-set-x-mid', '').strip()
            if new_mid:
                self.session.headers['X-MID'] = new_mid
            
            new_ds_user_id = resp_headers.get('ig-set-ig-u-ds-user-id', '').strip()
            if new_ds_user_id:
                self.session.headers['IG-U-DS-User-ID'] = new_ds_user_id
                if new_ds_user_id != self.user_id:
                    self.user_id = new_ds_user_id
            
            new_www_claim = resp_headers.get('x-ig-set-www-claim', '').strip()
            if new_www_claim:
                self.session.headers['X-IG-WWW-Claim'] = new_www_claim
                
        except Exception as e:
            print(f"Response header guncelleme hatasi: {e}")
    
    def get_all_groups(self):
        """
        Tüm grupları getirir
        """
        url = f"{self.api_url}/direct_v2/inbox/"
        params = {
            'persistentBadging': 'true',
            'limit': 50,
            'thread_message_limit': 1
        }
        
        try:
            # Debug: gönderilen header'ları logla
            print(f"\n{'='*60}")
            print(f"🔍 GÖNDERİLEN HEADER'LAR:")
            for key, value in self.session.headers.items():
                # Token'ı kısalt
                if 'Authorization' in key:
                    print(f"   {key}: {str(value)[:50]}...")
                else:
                    print(f"   {key}: {value}")
            print(f"{'='*60}\n")
            
            response = self.session.get(url, params=params, timeout=15, allow_redirects=False)
            
            # Response header'larından yeni session bilgilerini yakala
            self._update_headers_from_response(response)
            
            print(f"📡 Instagram API Response Status: {response.status_code}")
            print(f"📡 Request URL: {response.url}")
            
            # x-stack header'ını kontrol et (distillery = iyi, www = kötü)
            x_stack = response.headers.get('x-stack', 'bilinmiyor')
            if x_stack == 'www':
                print(f"⚠️ x-stack: www → İstekler WEB katmanına yönlendiriliyor! Token/Header sorunu olabilir.")
            else:
                print(f"✅ x-stack: {x_stack}")
            
            print(f"📡 Response Headers (önemli olanlar):")
            important_headers = ['x-stack', 'ig-set-ig-u-rur', 'ig-set-ig-u-ds-user-id', 
                               'x-ig-set-www-claim', 'ig-set-x-mid', 'x-ig-origin-region',
                               'x-fb-client-ip-forwarded', 'x-fb-server-cluster-forwarded']
            for key in important_headers:
                value = response.headers.get(key)
                if value:
                    print(f"   {key}: {value}")
            if response.status_code != 200:
                print(f"📡 Full Response Body:\n{response.text}")
            
            # Redirect kontrolü
            if response.status_code in (301, 302, 303, 307, 308):
                redirect_url = response.headers.get('Location', 'Bilinmiyor')
                print(f"⚠️ Redirect tespit edildi: {redirect_url}")
                print(f"⚠️ Bu genellikle geçersiz token anlamına gelir!")
                return []
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    all_threads = data.get('inbox', {}).get('threads', [])
                    print(f"✅ {len(all_threads)} thread bulundu")
                except json.JSONDecodeError as e:
                    print(f"❌ JSON parse hatası: {e}")
                    print(f"❌ Response içeriği (ilk 500 karakter): {response.text[:500]}")
                    return []
                
                # Sadece grupları filtrele
                groups = []
                for thread in all_threads:
                    if len(thread.get('users', [])) > 1:
                        thread_title = thread.get('thread_title', '')
                        users = thread.get('users', [])
                        
                        if not thread_title:
                            usernames = [u.get('username', '') for u in users[:3]]
                            thread_title = ", ".join(usernames)
                            if len(users) > 3:
                                thread_title += f" +{len(users)-3}"
                        
                        groups.append({
                            'id': thread.get('thread_id'),
                            'title': thread_title,
                            'user_count': len(users),
                            'users': users
                        })
                
                print(f"✅ {len(groups)} grup filtrelendi")
                return groups
            else:
                print(f"❌ API hata döndü: {response.status_code}")
                print(f"❌ Response: {response.text[:500]}")
                return []
                
        except Exception as e:
            print(f"❌ Grup çekme hatası: {e}")
            return []
    
    def get_thread_messages(self, thread_id, limit=100, target_date=None, max_pages=None):
        """Grubun mesajlarını getirir - belirli bir tarihe kadar çekebilir"""
        url = f"{self.api_url}/direct_v2/threads/{thread_id}/"
        
        all_messages = []
        cursor = None
        max_iterations = max_pages if max_pages else 50  # Eğer max_pages verilmişse onu kullan
        turkey_tz = pytz.timezone('Europe/Istanbul')
        
        # Eğer hedef tarih belirtildiyse, o tarihe kadar çek
        target_ts = None
        if target_date:
            target_ts = int(target_date.timestamp() * 1000000)
            # Hedef tarihi Türkiye saatine çevir
            target_date_tr = target_date.astimezone(turkey_tz)
            print(f"Hedef tarih (GMT+3): {target_date_tr.strftime('%Y-%m-%d %H:%M:%S')}")
        
        for i in range(max_iterations):
            params = {
                'limit': limit,
                'direction': 'older'  # Eski mesajları çek
            }
            if cursor:
                params['cursor'] = cursor
                params['direction'] = 'older'
            
            # Debug: İstek parametrelerini göster
            if i == 0:
                print(f"İlk istek parametreleri: {params}")
            
            try:
                response = self.session.get(url, params=params, timeout=60)
                
                # Response header'larından yeni session bilgilerini yakala
                self._update_headers_from_response(response)
                
                if response.status_code == 200:
                    data = response.json()
                    thread_data = data.get('thread', {})
                    messages = thread_data.get('items', [])
                    
                    if messages:
                        all_messages.extend(messages)
                        print(f"Sayfa {i+1}: {len(messages)} mesaj alındı. Toplam: {len(all_messages)}")
                        
                        # En eski mesajı kontrol et
                        if messages:
                            oldest_msg_ts = int(messages[-1].get('timestamp', 0))
                            oldest_date_utc = datetime.fromtimestamp(oldest_msg_ts / 1000000, tz=pytz.UTC)
                            oldest_date_tr = oldest_date_utc.astimezone(turkey_tz)
                            print(f"  En eski mesaj tarihi (GMT+3): {oldest_date_tr.strftime('%Y-%m-%d %H:%M:%S')}")
                            
                            # Eğer hedef tarihe ulaştıysak ve yeterli mesaj varsa dur
                            if target_ts and oldest_msg_ts < target_ts:
                                print(f"  Hedef tarihe ulaşıldı.")
                                # Hedef tarihten önce en az 100 mesaj daha çek
                                if i >= 2:  # En az 3 sayfa çektikten sonra dur
                                    print(f"  Yeterli mesaj çekildi, durduruluyor.")
                                    break
                        
                        # Check if there are more messages
                        has_older = thread_data.get('has_older')
                        oldest_cursor = thread_data.get('oldest_cursor')
                        prev_cursor = thread_data.get('prev_cursor')
                        
                        # Debug bilgileri
                        print(f"  has_older: {has_older}, oldest_cursor: {oldest_cursor is not None}, prev_cursor: {prev_cursor is not None}")
                        
                        # Cursor varsa, has_older ne olursa olsun devam et
                        next_cursor = oldest_cursor or prev_cursor
                        
                        # max_pages=1 ise sadece ilk sayfayı al
                        if max_pages and i >= max_pages - 1:
                            print(f"  Maksimum sayfa sayısına ({max_pages}) ulaşıldı")
                            break
                        
                        if next_cursor and i < 10:  # İlk 10 sayfada cursor varsa devam et
                            cursor = next_cursor
                            print(f"  Cursor mevcut, sonraki sayfaya geçiliyor (Sayfa {i+2})")
                            continue
                        elif has_older:
                            if next_cursor:
                                cursor = next_cursor
                                print(f"  has_older:true ve cursor mevcut, devam ediliyor")
                            else:
                                print("  has_older:true ama cursor yok, durduruluyor")
                                break
                        else:
                            # has_older:false ve 10 sayfayı geçtik
                            print(f"  Mesaj çekme tamamlandı (Sayfa {i+1})")
                            break
                    else:
                        break
                else:
                    print(f"Mesaj çekme hatası: HTTP {response.status_code}")
                    if response.status_code == 429:
                        print("  Rate limit'e takıldı! Biraz bekleyip tekrar deneyin.")
                    elif response.status_code == 401:
                        print("  Oturum hatası! Bearer Token'ı güncellemeniz gerekebilir.")
                    break
                    
            except Exception as e:
                print(f"Mesaj çekme hatası: {str(e)}")
                break
        
        print(f"Toplam {len(all_messages)} mesaj çekildi")
        return all_messages
    
    def get_thread_media_shares(self, thread_id, limit=50, start_timestamp=None, end_timestamp=None):
        """
        Grubun medya paylaşımlarını /media/ endpoint'inden çeker.
        paylasim.txt formatına uygun şekilde çalışır.
        """
        url = f"{self.api_url}/direct_v2/threads/{thread_id}/media/"
        
        all_media = []
        max_timestamp = None
        
        # Türkiye saati
        turkey_tz = pytz.timezone('Europe/Istanbul')
        
        print(f"Medya paylaşımları çekiliyor: {thread_id}")
        
        # Pagination döngüsü
        print(f"🚀 Pagination başlatılıyor, TARİH ARALIĞINDAKİ TÜM VERİLER ÇEKİLECEK (Limit Yok)...", flush=True)
        page_count = 0
        while True:
            page_count += 1
            
            # Her istekte maksimum 100 öğe iste
            params = {
                'limit': 100, 
                'media_type': 'media_shares'
            }
            
            if max_timestamp:
                params['max_timestamp'] = max_timestamp
            
            print(f"📡 API İsteği gönderiliyor (Sayfa {page_count})... URL: {url} Params: {params}", flush=True)
            print(f"📡 API İsteği gönderiliyor (Sayfa {page_count})... URL: {url} Params: {params}", flush=True)
            
            retry_count = 0
            max_retries = 5
            success = False
            
            while retry_count < max_retries:
                try:
                    # Timeout süresi
                    response = self.session.get(url, params=params, timeout=15)
                    self._update_headers_from_response(response)
                    
                    if response.status_code == 200:
                        success = True
                        break # Başarılı, retry döngüsünden çık
                    elif response.status_code == 429:
                        wait_time = (retry_count + 1) * 15 # 15, 30, 45, 60... saniye bekle
                        print(f"⚠️ Rate limit (429)! {wait_time} saniye bekleniyor... (Deneme {retry_count+1}/{max_retries})", flush=True)
                        import time
                        time.sleep(wait_time)
                        retry_count += 1
                    else:
                        print(f"⚠️ API Hata kodu döndü: {response.status_code}. 5 saniye bekleyip tekrar denenecek. (Deneme {retry_count+1}/{max_retries})", flush=True)
                        import time
                        time.sleep(5)
                        retry_count += 1
                except Exception as e:
                    print(f"⚠️ İstek sırasında ağ hatası: {str(e)}. 5 saniye bekleniyor...", flush=True)
                    import time
                    time.sleep(5)
                    retry_count += 1

            if not success:
                 print(f"❌ {max_retries} deneme başarısız oldu. Pagination durduruluyor.", flush=True)
                 break

            # Buraya geldiysek response 200 dönmüştür
            print(f"✅ Yanıt alındı: Status Code {response.status_code}", flush=True)
            
            try:
                data = response.json()
                items = data.get('items', [])
                
                if not items:
                    print("📭 Instagram'dan boş yanıt döndü (Daha fazla geçmiş veri yok).", flush=True)
                    break
                
                print(f"📦 Sayfa {page_count}: {len(items)} medya öğesi alındı.", flush=True)
                
                # Sayfadaki en yeni ve en eski timestamp'i bul
                page_timestamps = [int(x.get('timestamp', 0)) for x in items]
                newest_ts = max(page_timestamps) if page_timestamps else 0
                oldest_ts = min(page_timestamps) if page_timestamps else 0

                if newest_ts and oldest_ts:
                        newest_date = datetime.fromtimestamp(newest_ts/1000000).strftime('%Y-%m-%d %H:%M:%S')
                        oldest_date = datetime.fromtimestamp(oldest_ts/1000000).strftime('%Y-%m-%d %H:%M:%S')
                        print(f"debug_date: Sayfa Verisi Aralığı: {newest_date} --- {oldest_date}", flush=True)

                
                # Eğer sayfanın EN YENİSİ bile bizim başlangıçtan eskiyse, artık durabiliriz.
                # start_date string'ini elde edelim, sadece loglama için
                log_start_date = "Belirtilmedi"
                if start_timestamp:
                    log_start_date = datetime.fromtimestamp(start_timestamp/1000000).strftime('%Y-%m-%d')

                if start_timestamp and newest_ts < start_timestamp:
                        print(f"🛑 Tüm sayfa istenen tarihten eski ({newest_date} < {log_start_date}), analiz tamamlandı.", flush=True)
                        return all_media

                # Filtreleme ve toplama
                items_added = 0
                
                for item in items:
                    item_ts = int(item.get('timestamp', 0))
                    
                    # Timestamp kontrolü
                    if start_timestamp and item_ts < start_timestamp:
                        # Bu item çok eski, ekleme.
                        # Ama döngüyü hemen kırma, belki bu sayfada karışık veri vardır.
                        continue
                    
                    # İstenilen aralıkta ise ekle
                    if end_timestamp and item_ts > end_timestamp:
                        continue
                        
                    all_media.append(item)
                    items_added += 1
                
                print(f"➕ Bu sayfadan {items_added} adet medya eklendi. Toplam: {len(all_media)}", flush=True)
                
                # Eğer bu sayfadaki en eski mesaj, bizim başlangıcımızdan eskiyse
                # ve akış kronolojikse (Instagram öyledir), daha geriye gitmeye gerek yok.
                if start_timestamp and oldest_ts < start_timestamp:
                    print(f"🏁 Başlangıç tarihinden geriye gidildi ({oldest_date} < {log_start_date}), analiz tamamlandı.", flush=True)
                    break

                # Sonraki sayfa için timestamp güncelle (cursor)
                last_item = items[-1]
                old_cursor = max_timestamp 
                
                # Pagination stratejisi: next_max_id öncelikli
                next_max_id = data.get('next_max_id')
                
                print(f"🔍 API Yanıt Anahtarları: {list(data.keys())}", flush=True)
                if next_max_id:
                    print(f"🔗 Pagination için 'next_max_id' bulundu: {next_max_id}", flush=True)
                    # Bir sonraki istekte max_timestamp yerine cursor/max_id kullanılacak
                    # Ancak buradaki yapı max_timestamp üzerine kurulu.
                    # Eğer next_max_id varsa, onu safe bir şekilde parametreye eklememiz lazım.
                    # Döngünün başında params sözlüğünü ayarlarken bunu kontrol edeceğiz.
                    # Şimdilik max_timestamp değişkenine atayalım ama bu bir ID olabilir, timestamp değil.
                    # Bu yüzden params hazırlama kısmını değiştirmemiz gerek.
                    # HACK: max_timestamp değişkenini global cursor değişkeni gibi kullanalım.
                    max_timestamp = next_max_id
                else:
                    # Fallback: Timestamp kullan
                    max_timestamp = last_item.get('timestamp')
                    print(f"🔗 'next_max_id' yok, timestamp kullanılıyor: {max_timestamp}", flush=True)

                
                # Eğer cursor değişmediyse sonsuz döngüye girmemek için dur
                if old_cursor == max_timestamp:
                        print("⚠️ Cursor değişmedi (Sonsuz döngü riski), durduruluyor.", flush=True)
                        break
                
                # Debug: Son item tarihi
                # max_timestamp artık string bir ID olabilir, o yüzden int() çevrimi hata verebilir.
                # Sadece timestamp ise loglayalım.
                try:
                    if isinstance(max_timestamp, int) or (isinstance(max_timestamp, str) and max_timestamp.isdigit() and len(str(max_timestamp)) > 10):
                        pass 
                except:
                    pass
                
            except Exception as e:
                print(f"❌ Veri işleme hatası: {str(e)}", flush=True)
                import traceback
                traceback.print_exc()
                break
        
        print(f"🏁 Medya çekme tamamlandı. Toplam {len(all_media)} adet.", flush=True)
        return all_media
    
    def analyze_media_shares(self, thread_id, start_date, end_date):
        """Medya paylaşımlarını analiz eder"""
        # Türkiye saat dilimi
        turkey_tz = pytz.timezone('Europe/Istanbul')
        
        # Tarihleri Türkiye saat dilimine göre ayarla
        # Başlangıç: Gece 00:00 (tam günü kapsasın)
        start = datetime.strptime(start_date, "%Y-%m-%d")
        start = turkey_tz.localize(start.replace(hour=0, minute=0, second=0, microsecond=0))
        
        # Bitiş: Gece 23:59:59
        end = datetime.strptime(end_date, "%Y-%m-%d")
        end = turkey_tz.localize(end.replace(hour=23, minute=59, second=59, microsecond=999999))
        
        # UTC'ye çevir ve timestamp al
        start_utc = start.astimezone(pytz.UTC)
        end_utc = end.astimezone(pytz.UTC)
        
        start_ts = int(start_utc.timestamp() * 1000000)
        end_ts = int(end_utc.timestamp() * 1000000)
        
        print(f"Tarih aralığı (GMT+3): {start.strftime('%Y-%m-%d %H:%M:%S')} - {end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Filtreleme aralığı timestamp: {start_ts} - {end_ts}")
        
        # Grup bilgilerini al
        groups = self.get_all_groups()
        selected_group = None
        for group in groups:
            if group['id'] == thread_id:
                selected_group = group
                break
        
        if not selected_group:
            return None
        
        # Kullanıcı sözlüğü - @ işaretini temizle
        users_dict = {
            str(u.get('pk')): u.get('username', 'Bilinmeyen').lstrip('@')
            for u in selected_group['users']
        }
        
        # Önce ilk sayfayı çek ve kontrol et
        print(f"Mesajları kontrol ediliyor...")
        initial_messages = self.get_thread_messages(thread_id, limit=100, target_date=None, max_pages=1)
        
        # İlk sayfada istenen tarih aralığında mesaj var mı?
        has_messages_in_range = False
        if initial_messages:
            for msg in initial_messages:
                msg_ts = int(msg.get('timestamp', 0))
                if start_ts <= msg_ts <= end_ts:
                    has_messages_in_range = True
                    break
            
            # En eski mesajın tarihini kontrol et
            oldest_msg_ts = int(initial_messages[-1].get('timestamp', 0))
            oldest_date = datetime.fromtimestamp(oldest_msg_ts / 1000000, tz=pytz.UTC)
            oldest_date_tr = oldest_date.astimezone(turkey_tz)
            
            print(f"İlk sayfadaki en eski mesaj: {oldest_date_tr.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"İstenen aralıkta mesaj var mı: {has_messages_in_range}")
        
        # Eğer ilk sayfada mesaj varsa veya en eski mesaj istenen tarihten yeniyse, daha fazla çek
        if has_messages_in_range or (oldest_msg_ts > start_ts):
            # En eski mesaj istenen tarihten yeniyse, o tarihe kadar çek
            if oldest_msg_ts > start_ts:
                # Sadece 2 gün geriye git (daha az agresif)
                target_date = start_utc - timedelta(days=2)
                target_date_tr = target_date.astimezone(turkey_tz)
                print(f"Daha eski mesajlar gerekli, hedef tarih (GMT+3): {target_date_tr.strftime('%Y-%m-%d %H:%M:%S')}")
                messages = self.get_thread_messages(thread_id, target_date=target_date)
            else:
                # İlk sayfada yeterli mesaj var
                print(f"Yeterli mesaj mevcut, ek çekme yapılmıyor")
                messages = initial_messages
        else:
            # İstenen tarih aralığı çok eski, mesaj yok
            print(f"Bu tarih aralığında mesaj bulunamadı")
            messages = initial_messages
        
        # Medya içeriklerini filtrele
        media_content = []
        turkey_tz = pytz.timezone('Europe/Istanbul')
        
        print(f"Toplam mesaj sayısı: {len(messages)}")
        filtered_count = 0
        debug_count = 0
        
        for msg in messages:
            msg_ts = int(msg.get('timestamp', 0))
            
            # Debug: ilk 5 mesajın timestamp'ini kontrol et
            if debug_count < 5:
                msg_time = datetime.fromtimestamp(msg_ts / 1000000, tz=pytz.UTC)
                msg_time_tr = msg_time.astimezone(turkey_tz)
                print(f"Debug Mesaj {debug_count + 1} (GMT+3): {msg_time_tr.strftime('%Y-%m-%d %H:%M:%S')}")
                debug_count += 1
            
            # Tarih aralığına göre filtrele
            if start_ts <= msg_ts <= end_ts:
                filtered_count += 1
                item_type = msg.get('item_type')
                
                # Debug: Tüm item_type'ları göster
                if item_type and debug_count < 10:
                    print(f"Item type görüldü: {item_type}")
                    if item_type == 'clip':
                        print(f"CLIP/REELS bulundu! Veri yapısı: {json.dumps(msg.get('clip', {}), indent=2)[:500]}")
                    # Placeholder'ları da kontrol et - bunlar Reels olabilir
                    if item_type == 'placeholder':
                        # Placeholder içinde media_share varsa kontrol et
                        if msg.get('media_share'):
                            media_type = msg.get('media_share', {}).get('media_type')
                            print(f"Placeholder içinde media_share var, media_type: {media_type}")
                            # Eğer media_type 2 ise bu video/reels olabilir
                            if media_type == 2:
                                print(f"Video/Reels tespit edildi (placeholder içinde)")
                        # Diğer olası anahtarları kontrol et
                        for key in ['clip', 'reel', 'felix_share', 'raven_media']:
                            if msg.get(key):
                                print(f"Placeholder içinde {key} bulundu!")
                
                # Reels için genişletilmiş kontrol - placeholder'ları da ekle
                if item_type in ['clip', 'media_share', 'story_share', 'media', 'reel_share', 'felix_share', 'placeholder']:
                    sender_id = str(msg.get('user_id', ''))
                    sender_name = users_dict.get(sender_id, 'Bilinmeyen').lstrip('@')
                    
                    # Timestamp'i Türkiye saatine çevir
                    timestamp = int(msg.get('timestamp', 0)) / 1000000
                    time_obj_utc = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
                    time_obj_tr = time_obj_utc.astimezone(turkey_tz)
                    
                    content_info = {
                        'datetime': time_obj_tr.strftime('%d.%m.%Y %H:%M'),
                        'sharer': sender_name,
                        'type': item_type,
                        'owner': None,
                        'type_display': '',
                        'url': None,
                        'media_code': None
                    }
                    
                    # İçerik tipine göre detayları ekle
                    if item_type == 'clip' or item_type == 'reel_share':
                        # Farklı Reels veri yapılarını kontrol et
                        clip_data = None
                        
                        # Önce doğrudan clip anahtarını kontrol et
                        if msg.get('clip'):
                            # Bazen clip doğrudan obje olabilir
                            if isinstance(msg.get('clip'), dict):
                                # clip.clip yapısı
                                if msg.get('clip', {}).get('clip'):
                                    clip_data = msg.get('clip', {}).get('clip', {})
                                # Doğrudan clip yapısı
                                else:
                                    clip_data = msg.get('clip', {})
                        
                        # reel_share yapısını kontrol et
                        elif msg.get('reel_share'):
                            reel_share = msg.get('reel_share', {})
                            if reel_share.get('media'):
                                clip_data = reel_share.get('media', {})
                            elif reel_share.get('reel'):
                                clip_data = reel_share.get('reel', {})
                            else:
                                clip_data = reel_share
                        
                        # felix_share (eski Reels formatı) kontrolü
                        elif msg.get('felix_share'):
                            felix_share = msg.get('felix_share', {})
                            if felix_share.get('video'):
                                clip_data = felix_share.get('video', {})
                            else:
                                clip_data = felix_share
                        
                        if clip_data:
                            # Owner bilgisini bul
                            if clip_data.get('user'):
                                content_info['owner'] = clip_data.get('user', {}).get('username', 'Bilinmeyen').lstrip('@')
                            elif clip_data.get('owner'):
                                content_info['owner'] = clip_data.get('owner', {}).get('username', 'Bilinmeyen').lstrip('@')
                            else:
                                content_info['owner'] = 'Bilinmeyen'
                            
                            content_info['type_display'] = 'Reels'
                            
                            # Media code'u bul - farklı konumlarda olabilir
                            media_code = (
                                clip_data.get('code') or 
                                clip_data.get('media_code') or
                                clip_data.get('media', {}).get('code') or
                                clip_data.get('pk') or  # Bazen pk kullanılıyor
                                clip_data.get('id')  # Veya id
                            )
                            
                            if media_code:
                                content_info['media_code'] = str(media_code)
                                # pk veya id ise farklı URL formatı olabilir
                                if clip_data.get('code'):
                                    content_info['url'] = f'https://www.instagram.com/reel/{media_code}/'
                                else:
                                    content_info['url'] = f'https://www.instagram.com/reel/{media_code}/'
                        else:
                            # Clip data bulunamazsa debug için
                            print(f"UYARI: Reels verisi işlenemedi. item_type: {item_type}")
                            print(f"Mesaj anahtarları: {list(msg.keys())[:20]}")
                        
                    elif item_type == 'placeholder':
                        # Placeholder içinde media_share kontrolü
                        # Eğer media_share yoksa, bu silinmiş/gizlenmiş bir Reels olabilir
                        if msg.get('media_share'):
                            media_share = msg.get('media_share', {})
                            media_type = media_share.get('media_type', 1)
                            
                            content_info['owner'] = media_share.get('user', {}).get('username', 'Bilinmeyen').lstrip('@')
                            
                            # Media type 2 = video/reels, 1 = fotoğraf, 8 = carousel
                            product_type = media_share.get('product_type', '')
                            
                            # Kesin Reels tespiti: product_type == 'clips' veya media_type == 2
                            if product_type == 'clips' or (media_type == 2 and product_type != 'feed'):
                                # Kesinlikle Reels
                                content_info['type_display'] = 'Reels'
                                media_code = media_share.get('code')
                                if media_code:
                                    content_info['media_code'] = media_code
                                    content_info['url'] = f'https://www.instagram.com/reel/{media_code}/'
                            elif media_type == 2:
                                # Video - feed değilse büyük ihtimalle Reels
                                content_info['type_display'] = 'Reels'
                                media_code = media_share.get('code')
                                if media_code:
                                    content_info['media_code'] = media_code
                                    content_info['url'] = f'https://www.instagram.com/reel/{media_code}/'
                            else:
                                # Normal gönderi
                                content_info['type_display'] = 'Gönderi'
                                media_code = media_share.get('code')
                                if media_code:
                                    content_info['media_code'] = media_code
                                    content_info['url'] = f'https://www.instagram.com/p/{media_code}/'
                        else:
                            # Boş placeholder - skip
                            continue
                    
                    elif item_type == 'media_share' or item_type == 'felix_share':
                        media_share = msg.get('media_share', {})
                        media_type = media_share.get('media_type', 1)
                        
                        content_info['owner'] = media_share.get('user', {}).get('username', 'Bilinmeyen').lstrip('@')
                        
                        # Carousel içinde video kontrolu
                        if media_type == 8:  # Carousel
                            carousel_media = media_share.get('carousel_media', [])
                            has_video = False
                            video_item = None
                            for item in carousel_media:
                                if item.get('media_type') == 2:  # Video var
                                    has_video = True
                                    video_item = item
                                    break
                            
                            # Eğer carousel içinde video varsa, bunu Reels olarak işaretle
                            if has_video:
                                content_info['type_display'] = 'Reels'
                                media_code = media_share.get('code')
                                if media_code:
                                    content_info['media_code'] = media_code
                                    # Carousel içindeki videolar genelde Reels
                                    content_info['url'] = f'https://www.instagram.com/reel/{media_code}/'
                                # Video süresi varsa ekle
                                if video_item and video_item.get('video_duration'):
                                    content_info['video_duration'] = video_item.get('video_duration')
                                content_info['is_carousel_video'] = True
                                media_content.append(content_info)
                                continue  # Diğer kontrollere gerek yok
                        
                        # Reels tespit mantigi - geliştirilmiş
                        is_reels = False
                        reels_confidence = 0
                        
                        # 1. Kesin Reels göstergeleri
                        if media_share.get('product_type') == 'clips':
                            is_reels = True
                            reels_confidence = 100
                        elif media_share.get('is_reel_media'):
                            is_reels = True
                            reels_confidence = 95
                        elif 'clips_metadata' in media_share:
                            is_reels = True
                            reels_confidence = 90
                        
                        # 2. Video mu kontrol et
                        elif media_type == 2:
                            # Video - diğer özellikleri kontrol et
                            video_duration = media_share.get('video_duration', 0)
                            is_unified_video = media_share.get('is_unified_video')
                            has_audio = media_share.get('has_audio', True)
                            
                            # Kısa video (90 saniyeden kısa) genelde Reels
                            if video_duration and video_duration <= 90:
                                is_reels = True
                                reels_confidence = 80
                            # Product type yoksa ve kısa video ise muhtemelen Reels
                            elif not media_share.get('product_type'):
                                is_reels = True
                                reels_confidence = 70
                            # Feed olarak işaretlenmişse normal video
                            elif media_share.get('product_type') == 'feed':
                                is_reels = False
                            # Diğer durumlar için varsayılan olarak Reels kabul et
                            else:
                                is_reels = True
                                reels_confidence = 60
                        
                        # Tip belirleme
                        if is_reels:
                            content_info['type_display'] = 'Reels'
                            media_code = media_share.get('code')
                            if media_code:
                                content_info['media_code'] = media_code
                                content_info['url'] = f'https://www.instagram.com/reel/{media_code}/'
                        elif media_type == 2:
                            # Video ama Reels değil
                            content_info['type_display'] = 'Video'
                            media_code = media_share.get('code')
                            if media_code:
                                content_info['media_code'] = media_code
                                content_info['url'] = f'https://www.instagram.com/p/{media_code}/'
                        else:
                            # Fotoğraf veya carousel
                            content_info['type_display'] = 'Gönderi'
                            media_code = media_share.get('code')
                            if media_code:
                                content_info['media_code'] = media_code
                                content_info['url'] = f'https://www.instagram.com/p/{media_code}/'
                        
                    elif item_type == 'story_share':
                        story = msg.get('story_share', {})
                        if story.get('media'):
                            story_media = story.get('media', {})
                            content_info['owner'] = story_media.get('user', {}).get('username', 'Bilinmeyen').lstrip('@')
                            # Story URLs are temporary, but we can try to construct one
                            story_id = story_media.get('id') or story_media.get('pk')
                            if story_id and content_info['owner'] != 'Bilinmeyen':
                                content_info['url'] = f'https://www.instagram.com/stories/{content_info["owner"]}/{story_id}/'
                        else:
                            content_info['owner'] = sender_name
                        content_info['type_display'] = 'Hikaye'
                        
                    elif item_type == 'media':
                        content_info['owner'] = sender_name
                        content_info['type_display'] = 'Fotoğraf/Video'
                        # Try to get media URL from message
                        media_data = msg.get('media', {})
                        media_code = media_data.get('code')
                        if media_code:
                            content_info['media_code'] = media_code
                            content_info['url'] = f'https://www.instagram.com/p/{media_code}/'
                    
                    media_content.append(content_info)
        
        print(f"Tarih aralığında bulunan mesaj sayısı: {filtered_count}")
        print(f"Tarih aralığında bulunan medya sayısı: {len(media_content)}")
        
        # İstatistikleri hesapla
        type_counts = {}
        user_stats = {}
        
        for content in media_content:
            # Tip istatistikleri
            type_name = content['type_display']
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
            
            # Kullanıcı istatistikleri
            sharer = content['sharer']
            if sharer not in user_stats:
                user_stats[sharer] = {
                    'own': 0,
                    'others': 0,
                    'total': 0,
                    'shared_from': {}
                }
            
            user_stats[sharer]['total'] += 1
            
            if content['owner'] == sharer:
                user_stats[sharer]['own'] += 1
            else:
                user_stats[sharer]['others'] += 1
                owner = content['owner']
                if owner:
                    user_stats[sharer]['shared_from'][owner] = \
                        user_stats[sharer]['shared_from'].get(owner, 0) + 1
        
        return {
            'group': selected_group,
            'date_range': {
                'start': start.strftime('%d.%m.%Y'),
                'end': end.strftime('%d.%m.%Y')
            },
            'media_list': sorted(media_content, key=lambda x: x['datetime']),
            'statistics': {
                'total': len(media_content),
                'type_counts': type_counts,
                'user_stats': user_stats
            }
        }
    
    def _detect_media_type(self, item):
        """Medya öğesinin türünü belirler (Reels, Gönderi, Hikaye, vb.)"""
        item_type = item.get('item_type', '')
        
        # 1) Mesaj endpoint'inden gelen veriler (item_type mevcut)
        if item_type:
            if item_type in ('clip', 'reel_share', 'felix_share', 'xma_clip'):
                return 'Reels'
            if item_type in ('story_share', 'xma_story_share'):
                return 'Hikaye'
            if item_type in ('media', 'xma_media_share'):
                return 'Gönderi'
            if item_type == 'xma_link':
                return 'Diğer'
        
        # 2) media_share içiçe veri (mesaj endpoint'i)
        media_share = item.get('media_share', {})
        if media_share:
            return self._classify_media_obj(media_share)
        
        # 3) /media/ endpoint'inden gelen veriler - veri item['media'] altında
        media_obj = item.get('media', {})
        if media_obj and isinstance(media_obj, dict):
            return self._classify_media_obj(media_obj)
        
        # 4) Doğrudan item'ın kendisinde
        if item.get('product_type') or item.get('media_type') is not None:
            return self._classify_media_obj(item)
        
        # Fallback
        return 'Diğer'
    
    def _classify_media_obj(self, media_obj):
        """Bir medya objesini türüne göre sınıflandırır"""
        product_type = media_obj.get('product_type', '')
        media_type_val = media_obj.get('media_type', 1)
        
        # Kesin Reels göstergeleri
        if product_type == 'clips':
            return 'Reels'
        if media_obj.get('is_reel_media'):
            return 'Reels'
        if 'clips_metadata' in media_obj:
            return 'Reels'
        
        # Video kontrolü
        if media_type_val == 2:
            duration = media_obj.get('video_duration', 0)
            if duration and duration <= 90:
                return 'Reels'
            if not product_type or product_type != 'feed':
                return 'Reels'
            return 'Video'
        
        # Carousel
        if media_type_val == 8 or product_type == 'carousel_container':
            return 'Gönderi'
        
        # Fotoğraf (media_type == 1)
        if media_type_val == 1:
            return 'Gönderi'
        
        return 'Diğer'
    
    def analyze_weekly_participation(self, thread_id, week_start_date, week_end_date):
        """Haftalık katılım analizini yapar"""
        # Türkiye saat dilimi
        turkey_tz = pytz.timezone('Europe/Istanbul')
        
        # Tarihleri ayarla
        start = datetime.strptime(week_start_date, "%Y-%m-%d")
        start = turkey_tz.localize(start.replace(hour=0, minute=0, second=0, microsecond=0))
        end = datetime.strptime(week_end_date, "%Y-%m-%d")
        end = turkey_tz.localize(end.replace(hour=23, minute=59, second=59, microsecond=999999))
        
        # UTC'ye çevir
        start_utc = start.astimezone(pytz.UTC)
        end_utc = end.astimezone(pytz.UTC)
        start_ts = int(start_utc.timestamp() * 1000000)
        end_ts = int(end_utc.timestamp() * 1000000)
        
        # Grup bilgilerini al
        groups = self.get_all_groups()
        selected_group = None
        for group in groups:
            if group['id'] == thread_id:
                selected_group = group
                break
        
        if not selected_group:
            return None
        
        # Tüm grup üyelerini al
        all_members = {}
        for user in selected_group['users']:
            user_id = str(user.get('pk'))
            username = user.get('username', 'Bilinmeyen').lstrip('@')
            all_members[user_id] = {
                'username': username,
                'full_name': user.get('full_name', username),
                'profile_pic_url': user.get('profile_pic_url', ''),
                'participation_days': set(),  # Katılım yaptığı günler
                'total_shares': 0,
                'daily_shares': {},  # Günlük paylaşım sayıları
                'type_counts': {},  # Medya türü sayıları: {'Reels': 3, 'Gönderi': 1, ...}
                'daily_type_details': {},  # Günlük tür detayı: {'2026-02-15': {'Reels': 1}}
                'missing_days': 0,  # Eksik katılım gün sayısı
                'status': 'inactive',  # active, warning, inactive
                'text_messages': []  # Kullanıcının yazdığı text mesajlar
            }
        
        # Mesajları ve medyaları çek (yeni endpoint ile)
        print(f"Haftalık katılım analizi için medya verileri çekiliyor...")
        
        # Sadece medya olanları özel endpoint ile çek
        # paylasim.txt analizine göre /media/ endpoint'i user_id değil sender_id kullanıyor
        media_items = self.get_thread_media_shares(
            thread_id=thread_id, 
            limit=50, 
            start_timestamp=start_ts, 
            end_timestamp=end_ts
        )
        
        print(f"Toplam {len(media_items)} medya öğesi (/media/ endpoint).")
        
        # Hikaye paylaşımlarını da çekmek için mesajları da çek
        # /media/ endpoint'i story_share dönmüyor, mesaj endpoint'inden almalıyız
        print(f"Hikaye paylaşımları için mesajlar çekiliyor...")
        target_date = start_utc - timedelta(days=1)
        messages = self.get_thread_messages(thread_id, limit=100, target_date=target_date)
        
        # Mesajlardaki tüm item_type'ları say (debug)
        item_type_counts = {}
        story_count = 0
        for msg in messages:
            msg_ts = int(msg.get('timestamp', 0))
            if start_ts <= msg_ts <= end_ts:
                item_type = msg.get('item_type', 'boş')
                item_type_counts[item_type] = item_type_counts.get(item_type, 0) + 1
                # Hikaye paylaşımlarını ekle (xma_ prefix'li)
                if item_type in ('story_share', 'xma_story_share'):
                    media_items.append(msg)
                    story_count += 1
                
                # Text mesajları kullanıcı bazında topla
                if item_type == 'text':
                    sender_id = str(msg.get('user_id', ''))
                    text_content = msg.get('text', '')
                    if sender_id in all_members and text_content:
                        msg_time = datetime.fromtimestamp(
                            msg_ts / 1000000, tz=pytz.UTC
                        ).astimezone(turkey_tz)
                        all_members[sender_id]['text_messages'].append({
                            'text': text_content,
                            'time': msg_time.strftime('%d.%m %H:%M')
                        })
        
        print(f"\U0001f4ca Mesajlardaki item_type dağılımı: {item_type_counts}")
        print(f"Toplam {story_count} hikaye/reel paylaşımı mesajlardan eklendi. Toplam analiz edilecek: {len(media_items)}")
        
        # Analiz edilen en eski ve en yeni veriyi takip et
        analyzed_min_ts = None
        analyzed_max_ts = None

        # Medyaları analiz et
        for item in media_items:
            # sender_id (/media/ endpoint) veya user_id (mesaj endpoint) kullan
            sender_id = str(item.get('sender_id', '') or item.get('user_id', ''))
            
            # Timestamp mikrosaniye cinsinden
            item_ts = int(item.get('timestamp', 0))
            
            if start_ts <= item_ts <= end_ts:
                # Min/Max takip
                if analyzed_min_ts is None or item_ts < analyzed_min_ts:
                    analyzed_min_ts = item_ts
                if analyzed_max_ts is None or item_ts > analyzed_max_ts:
                    analyzed_max_ts = item_ts

                if sender_id in all_members:
                    # Tarihi al
                    timestamp = item_ts / 1000000
                    time_obj_utc = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
                    time_obj_tr = time_obj_utc.astimezone(turkey_tz)
                    
                    # Günü kaydet
                    day_str = time_obj_tr.strftime('%Y-%m-%d')
                    all_members[sender_id]['participation_days'].add(day_str)
                    all_members[sender_id]['total_shares'] += 1
                    
                    # Günlük paylaşım sayısını artır
                    if day_str not in all_members[sender_id]['daily_shares']:
                        all_members[sender_id]['daily_shares'][day_str] = 0
                    all_members[sender_id]['daily_shares'][day_str] += 1
                    
                    # Medya türünü belirle
                    media_type_label = self._detect_media_type(item)
                    
                    # Toplam tür sayısını artır
                    if media_type_label not in all_members[sender_id]['type_counts']:
                        all_members[sender_id]['type_counts'][media_type_label] = 0
                    all_members[sender_id]['type_counts'][media_type_label] += 1
                    
                    # Günlük tür detayını artır
                    if day_str not in all_members[sender_id]['daily_type_details']:
                        all_members[sender_id]['daily_type_details'][day_str] = {}
                    if media_type_label not in all_members[sender_id]['daily_type_details'][day_str]:
                        all_members[sender_id]['daily_type_details'][day_str][media_type_label] = 0
                    all_members[sender_id]['daily_type_details'][day_str][media_type_label] += 1
        
        # Tarih aralığındaki toplam gün sayısını hesapla
        total_days = (end.date() - start.date()).days + 1
        
        # Her üye için katılım durumunu hesapla
        # Eğer seçilen aralık 3 günden kısaysa, tüm günlere katılım zorunlu olsun
        # 3 gün ve fazlası için en az 3 gün kuralı geçerli
        if total_days < 3:
            weekly_requirement = total_days
        else:
            weekly_requirement = 3
        
        # Her gün için tarih stringi oluştur (katılım kontrolü için)
        all_days = set()
        current_date = start.date()
        while current_date <= end.date():
            all_days.add(current_date.strftime('%Y-%m-%d'))
            current_date += timedelta(days=1)
        
        for user_id, member_data in all_members.items():
            participation_count = len(member_data['participation_days'])
            
            # Gerçek eksik gün sayısını hesapla (katılım yapmadığı günler)
            actual_missing_days = len(all_days - member_data['participation_days'])
            member_data['missing_days'] = actual_missing_days
            
            if participation_count >= weekly_requirement:
                member_data['status'] = 'active'
            elif participation_count > 0:
                member_data['status'] = 'warning'
            else:
                member_data['status'] = 'inactive'
        
        # Gerçek analiz aralığını formatla
        actual_range_str = {}
        if analyzed_min_ts:
            min_ts_obj = datetime.fromtimestamp(analyzed_min_ts / 1000000, tz=pytz.UTC).astimezone(turkey_tz)
            actual_range_str['start'] = min_ts_obj.strftime('%d.%m.%Y')
        if analyzed_max_ts:
            max_ts_obj = datetime.fromtimestamp(analyzed_max_ts / 1000000, tz=pytz.UTC).astimezone(turkey_tz)
            actual_range_str['end'] = max_ts_obj.strftime('%d.%m.%Y')

        # Sonuçları döndür
        return {
            'group': selected_group,
            'week_range': {
                'start': start.strftime('%d.%m.%Y'),
                'end': end.strftime('%d.%m.%Y')
            },
            'actual_range': actual_range_str,
            'members': all_members,
            'weekly_requirement': weekly_requirement,
            'summary': {
                'total_members': len(all_members),
                'active_members': len([m for m in all_members.values() if m['status'] == 'active']),
                'warning_members': len([m for m in all_members.values() if m['status'] == 'warning']),
                'inactive_members': len([m for m in all_members.values() if m['status'] == 'inactive'])
            }
        }


# Global analyzer instance
analyzer = None

@app.route('/')
def index():
    """Ana sayfa"""
    return render_template('index.html')

@app.route('/api/init', methods=['POST'])
def init_analyzer():
    """Analyzer'ı aktif hesap ile başlat"""
    global analyzer
    try:
        with app.app_context():
            print("🚀 Analyzer başlatılıyor...")
            # Aktif hesabı bul
            active_token = BearerToken.query.filter_by(is_active=True).first()
            account_id = active_token.id if active_token else None
            analyzer = MediaShareAnalyzer(account_id=account_id)
            session['username'] = analyzer.username
            print(f"✅ Analyzer başarıyla başlatıldı: {analyzer.username}")
            return jsonify({
                'success': True,
                'username': analyzer.username
            })
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Analyzer başlatma hatası: {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500

@app.route('/api/groups', methods=['GET'])
def get_groups():
    """Grupları getir"""
    if not analyzer:
        return jsonify({'error': 'Analyzer başlatılmadı'}), 400
    
    try:
        groups = analyzer.get_all_groups()
        return jsonify({'groups': groups})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/active-account', methods=['GET'])
def get_active_account():
    """Aktif hesap bilgisini getir"""
    try:
        active_token = BearerToken.query.filter_by(is_active=True).first()
        if active_token:
            username = active_token.username
            if not username and analyzer:
                username = analyzer.username
            if not username:
                username = 'Bilinmeyen'
            
            return jsonify({
                'active': True,
                'username': username,
                'account_label': active_token.account_label or '',
                'has_device_id': bool(active_token.device_id),
                'has_android_id': bool(active_token.android_id),
                'has_user_agent': bool(active_token.user_agent)
            })
        else:
            return jsonify({'active': False, 'username': None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@app.route('/api/weekly-participation', methods=['POST'])
def weekly_participation():
    """Haftalık katılım analizini yap"""
    print(f"📡 API: Haftalık katılım analizi isteği alındı.", flush=True)
    
    if not analyzer:
        print("❌ Hata: Analyzer başlatılmamış!", flush=True)
        return jsonify({'error': 'Analyzer başlatılmadı'}), 400
    
    data = request.json
    thread_id = data.get('thread_id')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    
    print(f"ℹ️ Parametreler: ThreadID={thread_id}, Start={start_date}, End={end_date}", flush=True)
    print(f"ℹ️ Analyzer Username: {analyzer.username}", flush=True)
    
    if not all([thread_id, start_date, end_date]):
        return jsonify({'error': 'Eksik parametreler'}), 400
    
    try:
        result = analyzer.analyze_weekly_participation(thread_id, start_date, end_date)
        if result:
            # set'leri listeye çevir (JSON serializasyonu için)
            for member_data in result['members'].values():
                member_data['participation_days'] = list(member_data['participation_days'])
            return jsonify(result)
        else:
            return jsonify({'error': 'Analiz başarısız'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug-media-types', methods=['POST'])
def debug_media_types():
    """Media_share detaylarını incele - tüm alanları göster"""
    if not analyzer:
        return jsonify({'error': 'Analyzer başlatılmadı'}), 400
    
    data = request.json
    thread_id = data.get('thread_id')
    
    if not thread_id:
        return jsonify({'error': 'Thread ID gerekli'}), 400
    
    try:
        # Son mesajları çek
        messages = analyzer.get_thread_messages(thread_id, limit=100, max_pages=1)
        
        media_details = {
            'total_messages': len(messages),
            'media_shares_full': [],  # Tüm detaylar
            'reels_indicators': [],   # Reels olabilecek özellikler
            'stats': {
                'total_media_share': 0,
                'total_videos': 0,
                'with_video_versions': 0,
                'with_clips_metadata': 0,
                'with_product_type': 0
            }
        }
        
        for msg in messages:
            if msg.get('media_share'):
                media_share = msg['media_share']
                media_details['stats']['total_media_share'] += 1
                
                # Tüm alanları topla
                all_keys = list(media_share.keys())
                media_type = media_share.get('media_type')
                product_type = media_share.get('product_type')
                
                # Detaylı bilgi
                share_detail = {
                    'index': media_details['stats']['total_media_share'],
                    'all_keys': all_keys[:30],  # İlk 30 anahtar
                    'media_type': media_type,
                    'product_type': product_type,
                    'code': media_share.get('code'),
                    'taken_at': media_share.get('taken_at'),
                    'has_audio': media_share.get('has_audio'),
                    'video_duration': media_share.get('video_duration'),
                    'video_dash_manifest': bool(media_share.get('video_dash_manifest')),
                    'video_codec': media_share.get('video_codec'),
                    'number_of_qualities': media_share.get('number_of_qualities'),
                    'has_video_versions': 'video_versions' in media_share,
                    'video_versions_count': len(media_share.get('video_versions', [])),
                    'is_reel_media': media_share.get('is_reel_media'),
                    'clips_metadata_exists': 'clips_metadata' in media_share,
                    'clips_tab_pinned_user_ids': media_share.get('clips_tab_pinned_user_ids'),
                    'is_unified_video': media_share.get('is_unified_video'),
                    'is_dash_eligible': media_share.get('is_dash_eligible'),
                    'is_visual_reply_commenter_notice_enabled': media_share.get('is_visual_reply_commenter_notice_enabled'),
                    'commerciality_status': media_share.get('commerciality_status'),
                    'sharing_friction_info': bool(media_share.get('sharing_friction_info')),
                    'original_media_has_visual_reply_media': media_share.get('original_media_has_visual_reply_media')
                }
                
                # Video mu?
                if media_type == 2:
                    media_details['stats']['total_videos'] += 1
                    
                    # Video versiyonları varsa say
                    if share_detail['has_video_versions']:
                        media_details['stats']['with_video_versions'] += 1
                    
                    # Clips metadata varsa
                    if share_detail['clips_metadata_exists']:
                        media_details['stats']['with_clips_metadata'] += 1
                    
                    # Product type varsa
                    if product_type:
                        media_details['stats']['with_product_type'] += 1
                
                # Reels indikatörlerini kontrol et
                reels_score = 0
                indicators = []
                
                if media_type == 2:
                    indicators.append('video')
                    reels_score += 1
                    
                if product_type == 'clips':
                    indicators.append('product_type_clips')
                    reels_score += 10  # Kesin Reels
                    
                if share_detail['is_reel_media']:
                    indicators.append('is_reel_media_true')
                    reels_score += 8
                    
                if share_detail['clips_metadata_exists']:
                    indicators.append('has_clips_metadata')
                    reels_score += 5
                    
                if share_detail['is_unified_video']:
                    indicators.append('is_unified_video')
                    reels_score += 3
                    
                if share_detail['video_duration'] and share_detail['video_duration'] <= 90:
                    indicators.append(f'short_video_{share_detail["video_duration"]}s')
                    reels_score += 2
                    
                if not product_type and media_type == 2:
                    indicators.append('no_product_type_video')
                    reels_score += 1  # Product type yoksa muhtemelen Reels
                
                if reels_score > 0:
                    media_details['reels_indicators'].append({
                        'index': share_detail['index'],
                        'score': reels_score,
                        'indicators': indicators,
                        'code': share_detail['code'],
                        'duration': share_detail['video_duration']
                    })
                
                # İlk 5 media_share'i tam detaylı ekle
                if len(media_details['media_shares_full']) < 5:
                    media_details['media_shares_full'].append(share_detail)
        
        # Reels'leri skoruna göre sırala
        media_details['reels_indicators'].sort(key=lambda x: x['score'], reverse=True)
        
        return jsonify(media_details)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug-messages', methods=['POST'])
def debug_messages():
    """Mesajları debug modda incele - Reels'leri tespit et"""
    if not analyzer:
        return jsonify({'error': 'Analyzer başlatılmadı'}), 400
    
    data = request.json
    thread_id = data.get('thread_id')
    
    if not thread_id:
        return jsonify({'error': 'Thread ID gerekli'}), 400
    
    try:
        # Son 50 mesajı çek
        messages = analyzer.get_thread_messages(thread_id, limit=50, max_pages=1)
        
        debug_info = {
            'total_messages': len(messages),
            'message_types': {},
            'reels_found': [],
            'sample_structures': []
        }
        
        for msg in messages:
            item_type = msg.get('item_type')
            
            # Tüm mesaj tiplerini say
            if item_type:
                debug_info['message_types'][item_type] = debug_info['message_types'].get(item_type, 0) + 1
            
            # Reels olabilecek tüm tipleri kontrol et - placeholder dahil
            if item_type in ['clip', 'reel_share', 'felix_share', 'raven_media', 'placeholder']:
                reels_info = {
                    'type': item_type,
                    'keys': list(msg.keys())[:15],
                    'has_clip': 'clip' in msg,
                    'has_reel_share': 'reel_share' in msg,
                    'has_felix_share': 'felix_share' in msg,
                    'has_raven_media': 'raven_media' in msg
                }
                
                # Veri yapısını örnek olarak ekle
                if item_type == 'clip' and msg.get('clip'):
                    clip_sample = msg.get('clip', {})
                    # Sadece ilk seviye anahtarları
                    reels_info['clip_structure'] = list(clip_sample.keys())[:10]
                    if isinstance(clip_sample, dict) and clip_sample.get('clip'):
                        reels_info['nested_clip'] = list(clip_sample.get('clip', {}).keys())[:10]
                
                # Placeholder içinde media_share varsa analiz et
                if item_type == 'placeholder' and msg.get('media_share'):
                    media_share = msg.get('media_share', {})
                    reels_info['media_type'] = media_share.get('media_type')
                    reels_info['product_type'] = media_share.get('product_type')
                    reels_info['is_video'] = media_share.get('media_type') == 2
                    reels_info['code'] = media_share.get('code')
                    if media_share.get('media_type') == 2:
                        reels_info['likely_reels'] = True
                
                debug_info['reels_found'].append(reels_info)
            
            # İlk 3 mesajın tam yapısını örnek olarak ekle
            if len(debug_info['sample_structures']) < 3 and item_type:
                sample = {
                    'item_type': item_type,
                    'keys': list(msg.keys())[:20],
                    'timestamp': msg.get('timestamp')
                }
                
                # Eğer media içeriği varsa detaylı incele
                if item_type in ['clip', 'media_share', 'reel_share', 'felix_share']:
                    for key in ['clip', 'media_share', 'reel_share', 'felix_share', 'media', 'raven_media']:
                        if msg.get(key):
                            sample[f'has_{key}'] = True
                            if isinstance(msg.get(key), dict):
                                sample[f'{key}_keys'] = list(msg.get(key).keys())[:10]
                
                debug_info['sample_structures'].append(sample)
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Admin Panel Routes
ADMIN_PASSWORD = "seho"  # Admin şifresi

@app.route('/admin')
def admin_panel():
    """Admin paneli sayfası"""
    return render_template('admin.html')

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    """Admin girişi"""
    data = request.json
    password = data.get('password')
    
    if password == ADMIN_PASSWORD:
        session['admin_authenticated'] = True
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Yanlış şifre!'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    """Çıkış yap"""
    session.pop('admin_authenticated', None)
    return jsonify({'success': True})

@app.route('/api/admin/check-auth')
def check_admin_auth():
    """Oturum kontrolü"""
    return jsonify({'authenticated': session.get('admin_authenticated', False)})

@app.route('/api/admin/get-token')
def get_token():
    """Aktif token'ı ve tüm hesapları getir"""
    if not session.get('admin_authenticated'):
        return jsonify({'error': 'Yetkilendirme gerekli'}), 401
    
    try:
        # Aktif token
        token_record = BearerToken.query.filter_by(is_active=True).first()
        
        token_data = None
        if token_record:
            token_data = {
                'id': token_record.id,
                'account_label': token_record.account_label or '',
                'token': token_record.token,
                'android_id': token_record.android_id or '',
                'device_id': token_record.device_id or '',
                'user_agent': token_record.user_agent or '',
                'user_id': token_record.user_id,
                'username': token_record.username,
                'password': token_record.password or ''
            }
        
        # Tüm hesapları listele
        all_accounts = []
        for t in BearerToken.query.order_by(BearerToken.created_at.desc()).all():
            all_accounts.append({
                'id': t.id,
                'account_label': t.account_label or '',
                'username': t.username or 'Bilinmeyen',
                'user_id': t.user_id,
                'is_active': t.is_active,
                'has_device_id': bool(t.device_id),
                'has_android_id': bool(t.android_id),
                'has_user_agent': bool(t.user_agent),
                'created_at': t.created_at.strftime('%d.%m.%Y %H:%M') if t.created_at else ''
            })
        
        username = analyzer.username if analyzer else (token_record.username if token_record else 'Bilinmeyen')
        
        return jsonify({
            'token': token_data,
            'username': username,
            'accounts': all_accounts,
            'total_accounts': len(all_accounts)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/save-token', methods=['POST'])
def save_token():
    """Bearer Token'ı kaydet - Yeni hesap ekle veya mevcut hesabı güncelle"""
    if not session.get('admin_authenticated'):
        return jsonify({'error': 'Yetkilendirme gerekli'}), 401
    
    try:
        data = request.json
        token_input = data.get('token', '').strip()
        android_id_input = data.get('android_id', '').strip()
        user_agent_input = data.get('user_agent', '').strip()
        device_id_input = data.get('device_id', '').strip()
        account_label = data.get('account_label', '').strip()
        password_input = data.get('password', '').strip()
        account_id = data.get('account_id')  # Güncelleme için mevcut hesap ID'si
        
        if not token_input:
            return jsonify({'success': False, 'error': 'Token boş olamaz!'}), 400
        
        # Token'dan IGT:2: prefix'ini temizle
        clean_token = token_input
        if clean_token.startswith('Bearer '):
            clean_token = clean_token[7:]
        if clean_token.startswith('IGT:2:'):
            clean_token = clean_token[6:]
        clean_token = clean_token.strip()
        
        if not clean_token:
            return jsonify({'success': False, 'error': 'Geçersiz token formatı!'}), 400
        
        # device_id yoksa android_id'den oluştur
        if not device_id_input and android_id_input:
            android_clean = android_id_input.replace('android-', '')
            if len(android_clean) >= 32:
                device_id_input = f'{android_clean[:8]}-{android_clean[8:12]}-{android_clean[12:16]}-{android_clean[16:20]}-{android_clean[20:32]}'
            else:
                device_id_input = android_clean
        
        # Güncelleme mi yoksa yeni hesap mı?
        if account_id:
            existing_token = BearerToken.query.get(int(account_id))
            if existing_token:
                existing_token.token = clean_token
                existing_token.android_id = android_id_input or None
                existing_token.device_id = device_id_input or None
                existing_token.user_agent = user_agent_input or None
                existing_token.account_label = account_label or None
                existing_token.password = password_input or None
                db.session.commit()
                new_token = existing_token
                print(f"✓ Hesap güncellendi: {account_label or existing_token.username}")
            else:
                return jsonify({'success': False, 'error': 'Hesap bulunamadı!'}), 404
        else:
            # Yeni hesap ekle (eski hesapları SİLME!)
            new_token = BearerToken(
                token=clean_token,
                android_id=android_id_input or None,
                device_id=device_id_input or None,
                user_agent=user_agent_input or None,
                account_label=account_label or None,
                password=password_input or None,
                is_active=False
            )
            db.session.add(new_token)
            db.session.commit()
            print(f"✓ Yeni hesap eklendi: {account_label}")
        
        # Analyzer'ı yeni token ile başlat
        global analyzer
        try:
            analyzer = None
            analyzer = MediaShareAnalyzer(account_id=new_token.id)
            username = analyzer.username
            
            # Token kaydına user_id ve username ekle
            new_token.user_id = analyzer.user_id
            new_token.username = username
            db.session.commit()
            
            print(f"✓ Analyzer başlatıldı: {username}")
        except Exception as e:
            print(f"Analyzer başlatma hatası: {e}")
            username = 'Bilinmeyen'
        
        return jsonify({
            'success': True,
            'username': username,
            'account_id': new_token.id
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Create database tables and migrate existing schemas
with app.app_context():
    db.create_all()
    
    # Mevcut veritabanı için yeni sütunları ekle
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    
    # bearer_tokens tablosunda yeni sütunlar var mı kontrol et
    columns = [col['name'] for col in inspector.get_columns('bearer_tokens')]
    
    migrations = []
    if 'account_label' not in columns:
        migrations.append("ALTER TABLE bearer_tokens ADD COLUMN account_label VARCHAR(200)")
    if 'is_active' not in columns:
        migrations.append("ALTER TABLE bearer_tokens ADD COLUMN is_active BOOLEAN DEFAULT 0")
    if 'device_id' not in columns:
        migrations.append("ALTER TABLE bearer_tokens ADD COLUMN device_id VARCHAR(200)")
    if 'password' not in columns:
        migrations.append("ALTER TABLE bearer_tokens ADD COLUMN password VARCHAR(200)")
    
    for migration in migrations:
        try:
            db.session.execute(text(migration))
            print(f"✓ Migration: {migration}")
        except Exception as e:
            print(f"⚠ Migration atlandı: {e}")
    
    if migrations:
        db.session.commit()
        print(f"✓ {len(migrations)} migration uygulandı")
    
    # İlk hesabı otomatik aktif yap (eğer hiç aktif hesap yoksa)
    if 'is_active' in [col['name'] for col in inspector.get_columns('bearer_tokens')]:
        active_count = BearerToken.query.filter_by(is_active=True).count()
        if active_count == 0:
            first_token = BearerToken.query.first()
            if first_token:
                first_token.is_active = True
                db.session.commit()
                print(f"✓ İlk hesap otomatik aktif yapıldı: @{first_token.username}")
    
    print("[OK] Veritaban\u0131 haz\u0131r")

@app.route('/api/admin/clear-database', methods=['POST'])
def clear_database():
    """Veritabanını temizle"""
    if not session.get('admin_authenticated'):
        return jsonify({'error': 'Yetkilendirme gerekli'}), 401
    
    data = request.json or {}
    clear_accounts = data.get('clear_accounts', False)  # Hesapları da temizle
    
    try:
        # İlişkisel verileri temizle
        MediaShare.query.delete()
        Message.query.delete()
        WeeklyActivity.query.delete()
        GroupUser.query.delete()
        Group.query.delete()
        User.query.delete()
        SystemLog.query.delete()
        
        # Hesapları temizle (isteğe bağlı)
        if clear_accounts:
            BearerToken.query.delete()
        
        # Global analyzer'ı sıfırla
        global analyzer
        analyzer = None
        print("✓ Global analyzer sıfırlandı")
        
        # Log the action
        log = SystemLog(
            action='database_cleared',
            details=f'Database cleared. Accounts cleared: {clear_accounts}',
            status='success'
        )
        db.session.add(log)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Veritabanı temizlendi. Hesaplar: {"Silindi" if clear_accounts else "Korundu"}'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/database-stats')
def database_stats():
    """Veritabanı istatistiklerini getir"""
    if not session.get('admin_authenticated'):
        return jsonify({'error': 'Yetkilendirme gerekli'}), 401
    
    try:
        stats = {
            'cookies': Cookie.query.count(),
            'bearer_tokens': BearerToken.query.count(),
            'groups': Group.query.count(),
            'users': User.query.count(),
            'messages': Message.query.count(),
            'media_shares': MediaShare.query.count(),
            'weekly_activities': WeeklyActivity.query.count(),
            'system_logs': SystemLog.query.count()
        }
        
        # Get database file size
        db_path = os.path.join(basedir, 'instagram_analyzer.db')
        if os.path.exists(db_path):
            stats['database_size_mb'] = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        else:
            stats['database_size_mb'] = 0
        
        # Aktif hesap bilgisi
        active_token = BearerToken.query.filter_by(is_active=True).first()
        stats['active_account'] = active_token.username if active_token else None
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/activate-account', methods=['POST'])
def activate_account():
    """Belirli bir hesabı aktif et ve analyzer'ı yeniden başlat"""
    if not session.get('admin_authenticated'):
        return jsonify({'error': 'Yetkilendirme gerekli'}), 401
    
    global analyzer
    
    try:
        data = request.json
        account_id = data.get('account_id')
        
        if not account_id:
            return jsonify({'success': False, 'error': 'Hesap ID gerekli'}), 400
        
        # Tüm hesapları pasif yap
        BearerToken.query.update({'is_active': False})
        
        # Seçilen hesabı aktif yap
        target_account = BearerToken.query.get(int(account_id))
        if not target_account:
            db.session.rollback()
            return jsonify({'success': False, 'error': 'Hesap bulunamadı!'}), 404
        
        target_account.is_active = True
        db.session.commit()
        
        # Analyzer'ı yeni hesapla başlat
        try:
            analyzer = None
            analyzer = MediaShareAnalyzer(account_id=target_account.id)
            username = analyzer.username
            
            target_account.user_id = analyzer.user_id
            target_account.username = username
            db.session.commit()
            
            label = target_account.account_label or username
            print(f"✓ Aktif hesap değiştirildi: [{label}] @{username}")
            
            return jsonify({
                'success': True,
                'username': username,
                'account_label': label,
                'account_id': target_account.id
            })
        except Exception as e:
            return jsonify({'success': False, 'error': f'Analyzer başlatma hatası: {str(e)}'}), 500
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/delete-account', methods=['POST'])
def delete_account():
    """Belirli bir hesabı sil"""
    if not session.get('admin_authenticated'):
        return jsonify({'error': 'Yetkilendirme gerekli'}), 401
    
    global analyzer
    
    try:
        data = request.json
        account_id = data.get('account_id')
        
        if not account_id:
            return jsonify({'success': False, 'error': 'Hesap ID gerekli'}), 400
        
        target_account = BearerToken.query.get(int(account_id))
        if not target_account:
            return jsonify({'success': False, 'error': 'Hesap bulunamadı!'}), 404
        
        was_active = target_account.is_active
        label = target_account.account_label or target_account.username or 'Bilinmeyen'
        
        db.session.delete(target_account)
        db.session.commit()
        
        print(f"✓ Hesap silindi: [{label}]")
        
        # Eğer silinen hesap aktifse, başka bir hesabı aktif yap
        if was_active:
            remaining = BearerToken.query.first()
            if remaining:
                remaining.is_active = True
                db.session.commit()
                try:
                    analyzer = None
                    analyzer = MediaShareAnalyzer(account_id=remaining.id)
                    remaining.username = analyzer.username
                    remaining.user_id = analyzer.user_id
                    db.session.commit()
                    print(f"✓ Yeni aktif hesap: @{analyzer.username}")
                except Exception as e:
                    print(f"Analyzer başlatma hatası: {e}")
                    analyzer = None
            else:
                analyzer = None
        
        return jsonify({'success': True, 'message': f'Hesap silindi: {label}'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# INSTAGRAM LOGIN
# ============================================================

def instagram_login(username, password, device_id=None, android_id=None, user_agent=None):
    """
    Instagram Mobile API'ye login yapar.
    Başarılı olursa Bearer token ve device bilgilerini döndürür.
    """
    import base64
    import uuid as uuid_mod
    import hashlib
    import time as time_mod
    
    login_session = requests.Session(impersonate="chrome_android")
    
    # Device bilgileri yoksa üret
    if not android_id:
        android_id = uuid_mod.uuid4().hex[:16]
    if not device_id:
        clean_android = android_id.replace('android-', '')
        if len(clean_android) >= 32:
            device_id = f'{clean_android[:8]}-{clean_android[8:12]}-{clean_android[12:16]}-{clean_android[16:20]}-{clean_android[20:32]}'
        else:
            device_id = clean_android
    if not user_agent:
        user_agent = f'Instagram 415.0.0.36.76 Android (28/9; 240dpi; 720x1280; Asus; ASUS_I003DD; ASUS_I003DD; intel; tr_TR; {random.randint(100000000, 999999999)})'
    
    # Login headers
    android_id_full = f'android-{android_id}' if not android_id.startswith('android-') else android_id
    
    login_session.headers.update({
        'User-Agent': user_agent,
        'Accept-Language': 'tr-TR, en-US',
        'X-IG-App-ID': '567067343352427',
        'X-IG-Capabilities': '3brTv10=',
        'X-IG-Connection-Type': 'WIFI',
        'X-IG-Android-ID': android_id_full,
        'X-IG-App-Locale': 'tr_TR',
        'X-IG-Device-Locale': 'tr_TR',
        'X-IG-Mapped-Locale': 'tr_TR',
        'X-IG-Timezone-Offset': '10800',
        'X-FB-HTTP-Engine': 'Tigon/MNS/TCP',
        'X-FB-Client-IP': 'True',
        'X-FB-Server-Cluster': 'True',
        'Accept-Encoding': 'gzip, deflate',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    })
    
    # Login body
    login_data = {
        'username': username,
        'password': password,
        'device_id': device_id,
        'guid': str(uuid_mod.uuid4()),
        'phone_id': str(uuid_mod.uuid4()),
        'adid': str(uuid_mod.uuid4()),
        'google_tokens': '[]',
        'login_attempt_count': '0',
        'jazoest': str(2 ** 31 + int(hashlib.sha256(username.encode()).hexdigest()[:6], 16)),
    }
    
    # Step 1: Pre-login (kullanıcı adı kontrolü)
    try:
        pre_login_url = 'https://i.instagram.com/api/v1/usernamechecks/'
        pre_login_data = {
            'username': username,
            'email': '',
            'first_name': '',
            'client_id': str(uuid_mod.uuid4()),
        }
        pre_resp = login_session.post(pre_login_url, data=pre_login_data, timeout=15)
        print(f"Pre-login response: {pre_resp.status_code}")
    except Exception as e:
        print(f"Pre-login atlandı: {e}")
    
    # Step 2: Login
    login_url = 'https://i.instagram.com/api/v1/accounts/login/'
    
    try:
        resp = login_session.post(login_url, data=login_data, timeout=20)
        
        print(f"Login response status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            
            if data.get('status') == 'ok':
                user_data = data.get('user', {})
                logged_username = user_data.get('username', username)
                user_pk = str(user_data.get('pk', ''))
                
                # Cookie'leri al
                cookies = resp.cookies
                sessionid = cookies.get('sessionid', '')
                ds_user_id = cookies.get('ds_user_id', user_pk)
                csrftoken = cookies.get('csrftoken', '')
                
                if not sessionid:
                    # Session cookies'i login_session'dan al
                    try:
                        for cookie in login_session.cookies.jar:
                            if hasattr(cookie, 'name'):
                                if cookie.name == 'sessionid':
                                    sessionid = cookie.value
                                elif cookie.name == 'ds_user_id':
                                    ds_user_id = cookie.value
                                elif cookie.name == 'csrftoken':
                                    csrftoken = cookie.value
                    except Exception:
                        pass
                
                print(f"✓ Login başarılı: @{logged_username}")
                print(f"  sessionid: {'VAR' if sessionid else 'YOK'}")
                print(f"  ds_user_id: {ds_user_id}")
                
                # Bearer token oluştur (Instagram formatı)
                token_json = json.dumps({
                    'ds_user_id': ds_user_id,
                    'sessionid': sessionid,
                })
                bearer_token = base64.b64encode(token_json.encode()).decode()
                
                return {
                    'success': True,
                    'username': logged_username,
                    'user_id': ds_user_id or user_pk,
                    'token': bearer_token,
                    'device_id': device_id,
                    'android_id': android_id_full,
                    'user_agent': user_agent,
                    'csrftoken': csrftoken,
                    'sessionid': sessionid,
                }
            else:
                error_msg = data.get('message', 'Bilinmeyen hata')
                error_type = data.get('error_type', '')
                print(f"✗ Login başarısız: {error_msg}")
                
                if 'checkpoint' in error_type.lower() or 'challenge' in error_type.lower():
                    return {
                        'success': False,
                        'error': f'Doğrulama gerekiyor: {error_msg}',
                        'error_type': 'checkpoint',
                        'challenge_url': data.get('challenge', {}).get('url', ''),
                    }
                elif 'invalid' in error_type.lower() or 'user' in error_msg.lower():
                    return {
                        'success': False,
                        'error': 'Kullanıcı adı veya şifre yanlış!',
                        'error_type': 'invalid_credentials',
                    }
                else:
                    return {
                        'success': False,
                        'error': error_msg,
                        'error_type': error_type,
                    }
        
        elif resp.status_code == 400:
            try:
                data = resp.json()
                error_msg = data.get('message', 'Geçersiz istek')
                error_type = data.get('error_type', '')
                
                if 'checkpoint' in str(data).lower() or 'challenge' in str(data).lower():
                    return {
                        'success': False,
                        'error': f'Hesap doğrulama gerekiyor. Instagram uygulamasından giriş yapın.',
                        'error_type': 'checkpoint',
                    }
                
                return {
                    'success': False,
                    'error': error_msg,
                    'error_type': error_type,
                }
            except:
                return {'success': False, 'error': f'Login başarısız (HTTP 400)'}
        
        elif resp.status_code == 429:
            return {
                'success': False,
                'error': 'Çok fazla deneme! Birkaç dakika bekleyin.',
                'error_type': 'rate_limit',
            }
        
        else:
            return {
                'success': False,
                'error': f'Login başarısız (HTTP {resp.status_code})',
            }
    
    except Exception as e:
        print(f"Login exception: {e}")
        return {
            'success': False,
            'error': f'Bağlantı hatası: {str(e)}',
        }


@app.route('/login')
def login_page():
    """Login sayfası"""
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    """Instagram'a login yap ve hesabı DB'ye ekle"""
    global analyzer
    
    try:
        data = request.json
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        account_label = data.get('account_label', '').strip()
        device_id = data.get('device_id', '').strip() or None
        android_id = data.get('android_id', '').strip() or None
        user_agent = data.get('user_agent', '').strip() or None
        
        if not username or not password:
            return jsonify({'success': False, 'error': 'Kullanıcı adı ve şifre gerekli!'}), 400
        
        print(f"\n{'='*50}")
        print(f"Login denemesi: @{username}")
        print(f"{'='*50}")
        
        # Instagram'a login yap
        login_result = instagram_login(
            username=username,
            password=password,
            device_id=device_id,
            android_id=android_id,
            user_agent=user_agent,
        )
        
        if not login_result.get('success'):
            return jsonify(login_result), 400
        
        # Başarılı - DB'ye kaydet
        # Aynı kullanıcı adı ile hesap var mı kontrol et
        existing = BearerToken.query.filter_by(username=login_result['username']).first()
        
        if existing:
            # Güncelle
            existing.token = login_result['token']
            existing.device_id = login_result['device_id']
            existing.android_id = login_result['android_id']
            existing.user_agent = login_result['user_agent']
            existing.password = password
            existing.account_label = account_label or existing.account_label
            existing.user_id = login_result['user_id']
            db.session.commit()
            new_account = existing
            print(f"✓ Mevcut hesap güncellendi: @{login_result['username']}")
        else:
            # Yeni hesap ekle
            new_account = BearerToken(
                token=login_result['token'],
                username=login_result['username'],
                user_id=login_result['user_id'],
                device_id=login_result['device_id'],
                android_id=login_result['android_id'],
                user_agent=login_result['user_agent'],
                password=password,
                account_label=account_label or None,
                is_active=False,
            )
            db.session.add(new_account)
            db.session.commit()
            print(f"✓ Yeni hesap eklendi: @{login_result['username']}")
        
        # Log
        log = SystemLog(
            action='login_success',
            details=f'Instagram login successful: @{login_result["username"]}',
            status='success'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'username': login_result['username'],
            'account_id': new_account.id,
            'message': f'@{login_result["username"]} başarıyla giriş yaptı!',
        })
    
    except Exception as e:
        print(f"Login API hatasi: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/verify-token', methods=['POST'])
def verify_token():
    """Belirli bir hesabin token'ini Instagram API ile dogrula"""
    if not session.get('admin_authenticated'):
        return jsonify({'error': 'Yetkilendirme gerekli'}), 401
    
    try:
        data = request.json
        account_id = data.get('account_id')
        
        if not account_id:
            return jsonify({'success': False, 'error': 'Hesap ID gerekli'}), 400
        
        token_record = BearerToken.query.get(int(account_id))
        if not token_record:
            return jsonify({'success': False, 'error': 'Hesap bulunamad!'}), 404
        
        label = token_record.account_label or token_record.username or f'Hesap #{token_record.id}'
        
        # Dogrulama icin ayri bir session olustur
        verify_session = requests.Session(impersonate="chrome_android")
        
        # Header'lari ayarla
        android_id = token_record.android_id or 'android-a1b2c3d4e5f6g7h8'
        user_agent = token_record.user_agent or 'Instagram 415.0.0.36.76 Android (28/9; 240dpi; 720x1280; Asus; ASUS_I003DD; ASUS_I003DD; intel; tr_TR; 123456789)'
        
        bearer = token_record.token
        # Token zaten temiz olmali ama garanti olsun
        if bearer.startswith('Bearer '):
            bearer = bearer[7:]
        if bearer.startswith('IGT:2:'):
            bearer = bearer[6:]
        
        verify_session.headers.update({
            'User-Agent': user_agent,
            'Authorization': f'Bearer IGT:2:{bearer}',
            'X-IG-App-ID': '567067343352427',
            'X-IG-Capabilities': '3brTv10=',
            'X-IG-Connection-Type': 'WIFI',
            'X-IG-Android-ID': android_id,
            'Accept-Language': 'tr-TR, en-US',
            'X-IG-Timezone-Offset': '10800',
            'X-FB-HTTP-Engine': 'Tigon/MNS/TCP',
            'Accept-Encoding': 'gzip, deflate',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        })
        
        if token_record.device_id:
            verify_session.headers['X-IG-Device-ID'] = token_record.device_id
        
        # Session cookie'lerini ekle (Bearer token'dan decode et)
        ds_user_id = ''
        try:
            import base64
            decoded = base64.b64decode(token_record.token).decode()
            token_data = json.loads(decoded)
            sessionid = token_data.get('sessionid', '')
            ds_user_id = token_data.get('ds_user_id', '') or token_record.user_id or ''
            if sessionid:
                verify_session.cookies.set('sessionid', sessionid, domain='.instagram.com')
                verify_session.cookies.set('sessionid', sessionid, domain='i.instagram.com')
            if ds_user_id:
                verify_session.cookies.set('ds_user_id', ds_user_id, domain='.instagram.com')
                verify_session.cookies.set('ds_user_id', ds_user_id, domain='i.instagram.com')
            # csrftoken ekle
            verify_session.cookies.set('csrftoken', 'missing', domain='.instagram.com')
            verify_session.cookies.set('csrftoken', 'missing', domain='i.instagram.com')
        except Exception:
            pass
        
        # Dogrulama: Once current_user ile token gecerli mi kontrol et
        user = None
        status_code = 0
        try:
            resp = verify_session.get(
                'https://i.instagram.com/api/v1/accounts/current_user/',
                timeout=15
            )
            status_code = resp.status_code
            
            if status_code == 401 or status_code == 403:
                return jsonify({
                    'success': True,
                    'valid': False,
                    'message': 'Token expired veya yetkisiz!',
                    'account_id': token_record.id,
                    'status_code': status_code
                })
            
            if status_code == 429:
                return jsonify({
                    'success': True,
                    'valid': None,
                    'message': 'Rate limit! Biraz bekleyin.',
                    'account_id': token_record.id,
                    'status_code': status_code
                })
            
            if status_code == 200:
                resp_data = resp.json()
                if resp_data.get('status') == 'ok':
                    user = resp_data.get('user', {})
            
            if status_code != 200:
                return jsonify({
                    'success': True,
                    'valid': False,
                    'message': f'Dogrulama basarisiz (HTTP {status_code})',
                    'account_id': token_record.id,
                    'status_code': status_code
                })
        except Exception as e:
            return jsonify({
                'success': True,
                'valid': None,
                'message': f'Baglanti hatasi: {str(e)}',
                'account_id': token_record.id
            })
        
        # current_user takipci sayisi vermiyorsa, /info/ endpoint'ini dene
        uid = ds_user_id or (str(user.get('pk', '')) if user else '') or token_record.user_id or ''
        if user and not user.get('follower_count') and uid:
            try:
                info_resp = verify_session.get(
                    f'https://i.instagram.com/api/v1/users/{uid}/info/',
                    timeout=15
                )
                if info_resp.status_code == 200:
                    info_data = info_resp.json()
                    if info_data.get('status') == 'ok':
                        info_user = info_data.get('user', {})
                        # info_user'dan eksik alanları tamamla
                        if info_user.get('follower_count'):
                            user['follower_count'] = info_user['follower_count']
                        if info_user.get('following_count'):
                            user['following_count'] = info_user['following_count']
                        if info_user.get('full_name'):
                            user['full_name'] = info_user['full_name']
                        if info_user.get('is_private') is not None:
                            user['is_private'] = info_user['is_private']
                        if info_user.get('media_count'):
                            user['media_count'] = info_user['media_count']
                        if info_user.get('profile_pic_url'):
                            user['profile_pic_url'] = info_user['profile_pic_url']
            except Exception as e:
                print(f"User info hatasi: {e}")
        
        try:
            if user:
                username = user.get('username', token_record.username)
                full_name = user.get('full_name', '')
                is_private = user.get('is_private', False)
                media_count = user.get('media_count', 0)
                profile_pic_url = user.get('profile_pic_url', '')
                
                # Takipci sayisini birden fazla yerden dene
                follower_count = (
                    user.get('follower_count')
                    or user.get('edge_followed_by', {}).get('count', 0)
                    or 0
                )
                following_count = (
                    user.get('following_count')
                    or user.get('edge_follow', {}).get('count', 0)
                    or 0
                )
                
                follower_count = int(follower_count) if follower_count else 0
                following_count = int(following_count) if following_count else 0
                media_count = int(media_count) if media_count else 0
                
                # Token kaydini guncelle
                token_record.username = username
                if uid:
                    token_record.user_id = uid
                db.session.commit()
                
                print(f"Verify sonucu: @{username} - {follower_count} takipci, {following_count} takip")
                
                return jsonify({
                    'success': True,
                    'valid': True,
                    'username': username,
                    'full_name': full_name,
                    'is_private': is_private,
                    'follower_count': follower_count,
                    'following_count': following_count,
                    'media_count': media_count,
                    'profile_pic_url': profile_pic_url,
                    'message': 'Token aktif!',
                    'account_id': token_record.id
                })
            else:
                # Response 200 ama user yok veya status ok degil
                return jsonify({
                    'success': True,
                    'valid': False,
                    'message': 'Token gecersiz veya kullanici bulunamadi!',
                    'account_id': token_record.id
                })
        except Exception as e:
            print(f"Verify parse hatasi: {e}")
            return jsonify({
                'success': True,
                'valid': False,
                'message': f'Veri parse hatasi: {str(e)}',
                'account_id': token_record.id
            })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
