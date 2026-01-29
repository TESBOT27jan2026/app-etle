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
    # Mengambil argumen dari command line (dikirim oleh workflow.yml)
    INPUT_PLAT = sys.argv[1]
    INPUT_RANGKA = sys.argv[2]
    INPUT_MESIN = sys.argv[3]
    INPUT_ROW_ID = sys.argv[4]
except IndexError:
    print("❌ Error: Argumen kurang. Wajib: Plat, Rangka, Mesin, RowID")
    sys.exit(1)

print(f"🚀 Memproses: {INPUT_PLAT} | ID: {INPUT_ROW_ID}")

# --- 2. CONFIG BROWSER (HEADLESS) ---
def setup_browser():
    chrome_options = Options()
    chrome_options.add_argument("--headless") # Wajib buat GitHub Actions
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

# --- 3. LOGIKA DENDA (UPDATE: Cek Terbayar) ---
def hitung_denda(jenis_pelanggaran, status_bayar):
    # Cek dulu status bayarnya
    status_lower = str(status_bayar).lower()
    if any(x in status_lower for x in ["terbayar", "sudah", "selesai", "sidang"]):
        print("   -> Status Lunas/Sidang. Denda dinolkan.")
        return 0
        
    # Kalau belum bayar, baru hitung nominal
    text = str(jenis_pelanggaran).lower()
    if any(x in text for x in ["handphone", "ponsel", "wajar"]): return 750000
    elif "helm" in text: return 250000
    elif any(x in text for x in ["sabuk", "safety belt"]): return 250000
    elif any(x in text for x in ["dua orang", "berboncengan"]): return 250000
    elif any(x in text for x in ["rambu", "marka", "lampu", "arus", "jalur", "ganjil", "genap", "kecepatan", "stnk", "keabsahan"]): return 500000
    else: return 0

# --- 4. FUNGSI AMBIL DETAIL (Scraping Foto) ---
def scrape_detail_page(browser, url):
    print("   -> Mengambil Detail & Foto...")
    data_detail = {
        "Detail Jenis Pelanggaran": "-", "Dasar Hukum": "-", "Waktu Kejadian": "-",
        "Merk": "-", "Tipe": "-", "Warna": "-", "Nomor Rangka Detail": "-",
        "Model": "-", "Tahun": "-", "Nomor Mesin Detail": "-", "STNK Berlaku Sampai": "-",
        "Link Bukti Foto": "-"
    }
    
    try:
        browser.get(url)
        wait = WebDriverWait(browser, 10)
        # Tunggu container detail muncul
        container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.col-10")))
        
        # A. Ambil Foto
        try:
            img = container.find_element(By.TAG_NAME, "img")
            src = img.get_attribute('src')
            if src:
                # Pastikan URL lengkap
                full_url = "https://etle-pmj.id" + src if src.startswith('/') else src
                data_detail["Link Bukti Foto"] = full_url
        except: pass

        # B. Ambil Teks Detail
        full_text = container.text
        def extract(keyword):
            try: return full_text.split(keyword)[1].split('\n')[1].strip()
            except: return "-"

        data_detail['Detail Jenis Pelanggaran'] = extract('Data Pelanggaran')
        data_detail['Dasar Hukum'] = extract(data_detail['Detail Jenis Pelanggaran']) # Trik parsing
        data_detail['Waktu Kejadian'] = extract('Hari, Tanggal & Waktu')
        data_detail['Merk'] = extract('Merk')
        data_detail['Tipe'] = extract('Tipe')
        data_detail['Warna'] = extract('Warna')
        data_detail['Nomor Rangka Detail'] = extract('Nomor Rangka')
        data_detail['Model'] = extract('Model')
        data_detail['Tahun'] = extract('Tahun')
        data_detail['Nomor Mesin Detail'] = extract('Nomor Mesin')
        data_detail['STNK Berlaku Sampai'] = extract('STNK Berlaku Sampai')
        
    except Exception as e:
        print(f"   ❌ Gagal ambil detail: {e}")
        
    return data_detail

# --- 5. PROSES UTAMA (Main Logic) ---
def run_process():
    browser = setup_browser()
    
    # Template Data Default (Kalau Error/Aman)
    hasil = {
        "Status ETLE": "Gagal/Error", "Link Pengecekan": "-", 
        "Lokasi": "-", "Tanggal": "-", "Jenis Pelanggaran": "-", 
        "Status Pembayaran": "-", "Link Detail": "-", "Link Bukti Foto": "-",
        "Detail Jenis Pelanggaran": "-", "Dasar Hukum": "-", "Waktu Kejadian": "-",
        "Merk": "-", "Tipe": "-", "Warna": "-", "Nomor Rangka Detail": "-",
        "Model": "-", "Tahun": "-", "Nomor Mesin Detail": "-", 
        "STNK Berlaku Sampai": "-", "Estimasi Denda": 0
    }

    try:
        # Bersihkan Plat Nomor
        clean_plat = INPUT_PLAT.replace(' ', '').replace('-', '').upper()
        params = {'aksi': 'cek', 'nopol': clean_plat, 'norangka': INPUT_RANGKA, 'nomesin': INPUT_MESIN}
        target_url = "https://etle-pmj.id/?" + urlencode(params)
        hasil["Link Pengecekan"] = target_url
        
        print(f"🔍 Mengecek URL: {target_url}")
        browser.get(target_url)
        wait = WebDriverWait(browser, 20)
        
        # Tunggu Tabel atau Popup
        wait.until(EC.any_of(
            EC.presence_of_element_located((By.CLASS_NAME, "table")),
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.swal2-html-container"))
        ))

        # 1. Cek Popup "Data Tidak Ditemukan"
        try:
            popup = browser.find_element(By.CSS_SELECTOR, "div.swal2-html-container")
            if "tidak ditemukan" in popup.text.lower():
                print("✅ Hasil: Data Tidak Ditemukan (Aman)")
                hasil["Status ETLE"] = "Aman / Data Tidak Ditemukan"
                hasil["Estimasi Denda"] = 0
                return hasil
        except: pass

        # 2. Cek Tabel Pelanggaran
        rows = browser.find_elements(By.XPATH, "//tbody/tr")
        if len(rows) > 0:
            print(f"⚠️ DITEMUKAN {len(rows)} DATA PELANGGARAN!")
            
            # Ambil Baris Pertama (Terbaru)
            cols = rows[0].find_elements(By.TAG_NAME, "td")
            if len(cols) >= 4:
                hasil["Tanggal"] = cols[0].text
                hasil["Lokasi"] = cols[1].text
                hasil["Jenis Pelanggaran"] = cols[2].text
                hasil["Status Pembayaran"] = cols[3].text
                
                # Format Status Akhir untuk AppSheet
                status_str = hasil["Status Pembayaran"]
                if any(x in status_str.lower() for x in ["terbayar", "sudah", "selesai"]):
                     hasil["Status ETLE"] = f"Ada ETLE ({status_str})"
                else:
                     hasil["Status ETLE"] = "Ada ETLE (Belum Bayar)"
                
                # Ambil Link Detail
                try:
                    btn = rows[0].find_element(By.CSS_SELECTOR, "a.btn-secondary")
                    hasil["Link Detail"] = btn.get_attribute('href')
                except: pass

                # Hitung Denda (Penting!)
                hasil["Estimasi Denda"] = hitung_denda(hasil["Jenis Pelanggaran"], hasil["Status Pembayaran"])

                # Masuk Halaman Detail buat ambil Foto
                if hasil["Link Detail"] != "-":
                    detil_info = scrape_detail_page(browser, hasil["Link Detail"])
                    hasil.update(detil_info)

    except Exception as e:
        print(f"❌ Error Utama: {e}")
    finally:
        browser.quit()
        
    return hasil

# --- 6. KIRIM BALIK KE APPSHEET (Via API) ---
def push_to_appsheet(data):
    # Ambil Secrets dari GitHub Environment
    app_id = os.environ.get("APPSHEET_ID")
    access_key = os.environ.get("APPSHEET_KEY")
    
    if not app_id or not access_key:
        print("⛔ ERROR: APPSHEET_ID atau APPSHEET_KEY belum disetting di GitHub Secrets!")
        return

    url = f"https://api.appsheet.com/api/v2/apps/{app_id}/tables/Log_Cek/Action"
    
    payload = {
        "Action": "Edit",
        "Properties": {"Locale": "id-ID", "Timezone": "SE Asia Standard Time"},
        "Rows": [{
            "ID": INPUT_ROW_ID,
            # Data yang akan diupdate ke AppSheet
            "Status ETLE": data["Status ETLE"],
            "Estimasi Denda": str(data["Estimasi Denda"]),
            "Link Bukti Foto": data["Link Bukti Foto"],
            "Link Pengecekan": data["Link Pengecekan"],
            "Lokasi": data["Lokasi"],
            "Tanggal": data["Tanggal"],
            "Jenis Pelanggaran": data["Jenis Pelanggaran"],
            "Status Pembayaran": data["Status Pembayaran"],
            # Tambahan Detail
            "Detail Jenis Pelanggaran": data["Detail Jenis Pelanggaran"],
            "Dasar Hukum": data["Dasar Hukum"],
            "Waktu Kejadian": data["Waktu Kejadian"],
            "Merk": data["Merk"],
            "Tipe": data["Tipe"],
            "Warna": data["Warna"],
            "Nomor Rangka Detail": data["Nomor Rangka Detail"],
            "Nomor Mesin Detail": data["Nomor Mesin Detail"],
            "STNK Berlaku Sampai": data["STNK Berlaku Sampai"]
        }]
    }
    
    print("📤 Mengirim data ke AppSheet...")
    try:
        req = requests.post(url, headers={"applicationAccessKey": access_key}, json=payload)
        if req.status_code == 200:
            print("✅ SUKSES! AppSheet berhasil diupdate.")
        else:
            print(f"❌ GAGAL Update AppSheet: {req.status_code} | {req.text}")
    except Exception as e:
        print(f"❌ Error Koneksi: {e}")

if __name__ == "__main__":
    # Jalankan Proses
    result = run_process()
    
    # Tampilkan Hasil di Log GitHub
    print("\n--- HASIL AKHIR ---")
    print(json.dumps(result, indent=2))
    
    # Kirim ke AppSheet
    push_to_appsheet(result)
