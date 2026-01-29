import sys
import os
import requests
import json
import time
from urllib.parse import urlencode
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService

# --- 1. TERIMA INPUT DARI GITHUB ACTION ---
try:
    INPUT_PLAT = sys.argv[1]
    INPUT_RANGKA = sys.argv[2]
    INPUT_MESIN = sys.argv[3]
    INPUT_ROW_ID = sys.argv[4]
except IndexError:
    print("❌ Error: Argumen kurang.")
    sys.exit(1)

print(f"🚀 Memproses: {INPUT_PLAT}")

# --- 2. CONFIG BROWSER (ANTI-DETEKSI) ---
def setup_browser():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    # User Agent Pura-pura jadi Laptop Windows Beneran
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

# --- 3. LOGIKA DENDA ---
def hitung_denda(jenis_pelanggaran, status_bayar):
    status_lower = str(status_bayar).lower()
    if any(x in status_lower for x in ["terbayar", "sudah", "selesai", "sidang"]):
        return 0
    text = str(jenis_pelanggaran).lower()
    if any(x in text for x in ["handphone", "ponsel", "wajar"]): return 750000
    elif "helm" in text: return 250000
    elif any(x in text for x in ["sabuk", "safety belt"]): return 250000
    elif any(x in text for x in ["dua orang", "berboncengan"]): return 250000
    elif any(x in text for x in ["rambu", "marka", "lampu", "arus", "jalur", "ganjil", "genap", "kecepatan", "stnk", "keabsahan"]): return 500000
    else: return 0

# --- 4. FUNGSI AMBIL DETAIL ---
def scrape_detail_page(browser, url):
    data_detail = {"Link Bukti Foto": "-"}
    try:
        browser.get(url)
        wait = WebDriverWait(browser, 8)
        container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.col-10")))
        
        try:
            img = container.find_element(By.TAG_NAME, "img")
            src = img.get_attribute('src')
            if src:
                full_url = "https://etle-pmj.id" + src if src.startswith('/') else src
                data_detail["Link Bukti Foto"] = full_url
        except: pass

        full_text = container.text
        def extract(keyword):
            try: return full_text.split(keyword)[1].split('\n')[1].strip()
            except: return "-"

        cols_map = {
            'Detail Jenis Pelanggaran': 'Data Pelanggaran',
            'Waktu Kejadian': 'Hari, Tanggal & Waktu',
            'Merk': 'Merk', 'Tipe': 'Tipe', 'Warna': 'Warna',
            'Nomor Rangka Detail': 'Nomor Rangka', 'Nomor Mesin Detail': 'Nomor Mesin',
            'STNK Berlaku Sampai': 'STNK Berlaku Sampai'
        }
        for key, keyword in cols_map.items():
            data_detail[key] = extract(keyword)

    except Exception as e:
        print(f"   ⚠️ Gagal detail: {str(e)[:50]}")
    return data_detail

# --- 5. CORE PROCESS ---
def run_process():
    browser = setup_browser()
    # Default Hasil Awal (Kalau crash total, ini yang dikirim)
    hasil = {
        "Status ETLE": "System Error (Unknown)", 
        "Estimasi Denda": 0, 
        "Link Bukti Foto": "-"
    }

    try:
        clean_plat = INPUT_PLAT.replace(' ', '').replace('-', '').upper()
        params = {'aksi': 'cek', 'nopol': clean_plat, 'norangka': INPUT_RANGKA, 'nomesin': INPUT_MESIN}
        target_url = "https://etle-pmj.id/?" + urlencode(params)
        hasil["Link Pengecekan"] = target_url
        
        print(f"🔍 Cek URL: {target_url}")
        browser.get(target_url)
        wait = WebDriverWait(browser, 30) # Waktu tunggu dimaksimalkan 30 detik
        
        # Tunggu Tabel atau Popup
        wait.until(EC.any_of(
            EC.presence_of_element_located((By.CLASS_NAME, "table")),
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.swal2-html-container"))
        ))

        # Cek Aman
        try:
            popup = browser.find_element(By.CSS_SELECTOR, "div.swal2-html-container")
            if "tidak ditemukan" in popup.text.lower():
                hasil["Status ETLE"] = "Aman / Data Tidak Ditemukan"
                hasil["Estimasi Denda"] = 0
                return hasil
        except: pass

        # Cek Pelanggaran
        rows = browser.find_elements(By.XPATH, "//tbody/tr")
        if len(rows) > 0:
            cols = rows[0].find_elements(By.TAG_NAME, "td")
            if len(cols) >= 4:
                hasil["Tanggal"] = cols[0].text
                hasil["Lokasi"] = cols[1].text
                hasil["Jenis Pelanggaran"] = cols[2].text
                hasil["Status Pembayaran"] = cols[3].text
                
                status_str = hasil["Status Pembayaran"]
                if any(x in status_str.lower() for x in ["terbayar", "sudah", "selesai"]):
                     hasil["Status ETLE"] = f"Ada ETLE ({status_str})"
                else:
                     hasil["Status ETLE"] = "Ada ETLE (Belum Bayar)"
                
                hasil["Estimasi Denda"] = hitung_denda(hasil["Jenis Pelanggaran"], hasil["Status Pembayaran"])
                
                try:
                    btn = rows[0].find_element(By.CSS_SELECTOR, "a.btn-secondary")
                    link_detail = btn.get_attribute('href')
                    hasil.update(scrape_detail_page(browser, link_detail))
                except: pass

    except Exception as e:
        # --- BAGIAN INI YANG NANGKEP PESAN ERROR ---
        error_msg = str(e).lower()
        print(f"❌ CRASH LOG: {error_msg}")
        
        if "time-out" in error_msg or "timed out" in error_msg:
            reason = "Error: Website ETLE Lemot (Timeout)"
        elif "no such element" in error_msg:
            reason = "Error: Tampilan Web Berubah"
        elif "connection refused" in error_msg or "err_connection" in error_msg:
            reason = "Error: Gagal Koneksi Internet"
        elif "session deleted" in error_msg:
            reason = "Error: Browser Crash (Session)"
        else:
            # Ambil 50 huruf pertama dari error asli biar muat di HP
            reason = f"Error: {str(e)[:50]}"
            
        hasil["Status ETLE"] = reason
            
    finally:
        try:
            browser.quit()
        except: pass
        
    return hasil

# --- 6. KIRIM BALIK KE APPSHEET ---
def push_to_appsheet(data):
    app_id = os.environ.get("APPSHEET_ID")
    access_key = os.environ.get("APPSHEET_KEY")
    
    if not app_id or not access_key:
        print("⛔ API Key belum disetting!")
        return

    url = f"https://api.appsheet.com/api/v2/apps/{app_id}/tables/Log_Cek/Action"
    
    payload_data = {
        "ID": INPUT_ROW_ID,
        "Status ETLE": data.get("Status ETLE", "Unknown Error"),
        "Estimasi Denda": str(data.get("Estimasi Denda", 0)),
        "Link Bukti Foto": data.get("Link Bukti Foto", "-"),
        "Link Pengecekan": data.get("Link Pengecekan", "-"),
        "Lokasi": data.get("Lokasi", "-"),
        "Tanggal": data.get("Tanggal", "-"),
        "Jenis Pelanggaran": data.get("Jenis Pelanggaran", "-"),
        "Status Pembayaran": data.get("Status Pembayaran", "-"),
        "Detail Jenis Pelanggaran": data.get("Detail Jenis Pelanggaran", "-"),
        "Merk": data.get("Merk", "-"),
        "Tipe": data.get("Tipe", "-"),
        "Warna": data.get("Warna", "-"),
        "STNK Berlaku Sampai": data.get("STNK Berlaku Sampai", "-")
    }

    payload = {
        "Action": "Edit",
        "Properties": {"Locale": "id-ID", "Timezone": "SE Asia Standard Time"},
        "Rows": [payload_data]
    }
    
    try:
        req = requests.post(url, headers={"applicationAccessKey": access_key}, json=payload)
        print("✅ Data terkirim ke AppSheet")
        print(req.text)
    except Exception as e:
        print(f"❌ Gagal kirim: {e}")

if __name__ == "__main__":
    result = run_process()
    push_to_appsheet(result)
