import os
import pandas as pd
import requests

def perform_ai_analysis(csv_path: str, api_key: str):
    """
    S.P.E.A.R. AI Uçuş Analisti.
    """
    if not api_key:
        return "⚠️ Yapay Zeka (AI) analizi için geçerli bir Gemini API Anahtarı gereklidir."
        
    if not os.path.exists(csv_path):
        return "❌ Analiz edilecek CSV verisi bulunamadı."
        
    try:
        # Veriyi okuma ve özetleme
        df = pd.read_csv(csv_path)
        
        if df.empty:
            return "❌ CSV dosyası boş, analiz edilemedi."
            
        final_row = df.iloc[-1]
        max_g = df['G_Force'].max()
        max_q = df['Dyn_Pressure'].max()
        max_alt = df['Y'].max()
        
        # AI'a gidecek Prompt
        prompt = f"""
        Sen S.P.E.A.R. Uzay Ajansının Baş Telemetri Yapay Zekasısın. 
        Aşağıda son gerçekleşen roket fırlatma simülasyonunun özet telemetri verileri bulunmaktadır:
        
        - Maksimum İrtifa: {max_alt / 1000:.2f} km
        - Nihai İrtifa (Son Durum): {final_row['Y'] / 1000:.2f} km
        - Maksimum Hız: {df['Velocity'].max():.2f} m/s
        - Maksimum G-Kuvveti: {max_g:.2f} G
        - Maksimum Dinamik Basınç (Max-Q): {max_q / 1000:.2f} kPa
        - Ulaşılan Yörünge Tipi: {final_row.get('Orbit_Type', 'Bilinmiyor')}
        
        Ayrıca genel uçuş performansı istatistikleri şunlardır:
        {df[['Time', 'Velocity', 'Y', 'Mass', 'G_Force']].describe().to_string()}
        
        Lütfen bu uçuşun operasyonel başarısı, yapısal stresleri (G-Force ve Max-Q), hız verimliliği ve yörünge oturtma durumu hakkında uçuş kontrol ekibine profesyonel, net ve mühendislik terimleriyle harmanlanmış kısa bir 'Görev Sonu Değerlendirme Raporu' hazırla. 
        """
        
        # Gemini 1.5 Pro API Çagrisi
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            err_msg = response.json().get('error', {}).get('message', 'API Hatası')
            return f"❌ Yapay Zeka Modülü API Hatası: {err_msg}"
            
    except Exception as e:
        return f"🚨 Analiz İletişim Hatası: {str(e)}"
