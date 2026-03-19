"""
Instagram DM Analiz Sistemi - Test Scripti
Tüm önemli fonksiyonları test eder
"""
from curl_cffi import requests
import json
from datetime import datetime, timedelta

def test_system():
    """Ana test fonksiyonu"""
    print("="*60)
    print("INSTAGRAM DM ANALİZ SİSTEMİ - TEST")
    print("="*60)
    
    # 1. Analyzer'ı başlat
    print("\n1. Analyzer başlatılıyor...")
    init = requests.post('http://127.0.0.1:5000/api/init')
    if init.ok:
        data = init.json()
        print(f"✅ Başarılı! Kullanıcı: {data.get('username')}")
    else:
        print("❌ Başlatma hatası!")
        return
    
    # 2. Grupları kontrol et
    print("\n2. Gruplar alınıyor...")
    groups = requests.get('http://127.0.0.1:5000/api/groups')
    if groups.ok:
        group_list = groups.json()['groups']
        print(f"✅ {len(group_list)} grup bulundu")
        for i, g in enumerate(group_list[:3], 1):
            print(f"   {i}. {g['title']} ({g['user_count']} üye)")
    else:
        print("❌ Grup alma hatası!")
        return
    
    # 3. İlk grubu analiz et
    if group_list:
        print(f"\n3. İlk grup analiz ediliyor...")
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        analyze = requests.post('http://127.0.0.1:5000/api/analyze', json={
            'thread_id': group_list[0]['id'],
            'start_date': yesterday,
            'end_date': today
        })
        
        if analyze.ok:
            result = analyze.json()
            total = result['statistics']['total']
            types = result['statistics']['type_counts']
            
            print(f"✅ Analiz başarılı!")
            print(f"   Toplam: {total} medya")
            for tip, sayi in types.items():
                print(f"   • {tip}: {sayi}")
        else:
            print("❌ Analiz hatası!")
    
    print("\n" + "="*60)
    print("TEST TAMAMLANDI")
    print("="*60)

if __name__ == "__main__":
    test_system()