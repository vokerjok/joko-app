import os
import sys
import time
import random
import string
import requests
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# =========================================================
# ⚙️ KONFIGURASI (sesuaikan kalau perlu)
# =========================================================

TG_BOT_TOKEN = "8333206393:AAG8Z76SSbgAEAC1a3oPT8XhAF9t_rDOq3A"
TG_CHAT_ID = "-1003532458425"

PROFILE_PREFIX = "joko"
START_INDEX = 1

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720

CHROME_BINARY = "/usr/bin/google-chrome"
CHROMEDRIVER_PATH = "/usr/bin/chromedriver"  # pastikan ada (atau ubah)

BASE_PROFILE_DIR = "/root/chrome_profiles"
BASE_PATH = os.path.dirname(os.path.abspath(__file__))

EMAIL_FILE = os.path.join(BASE_PATH, "email.txt")
EMAILSHARE_FILE = os.path.join(BASE_PATH, "emailshare.txt")
MAPPING_FILE = os.path.join(BASE_PATH, "mapping_profil.txt")
HASIL_FILE = os.path.join(BASE_PATH, "hasil.txt")
AKUN_BERMASALAH = os.path.join(BASE_PATH, "akun_bermasalah.txt")

# =========================================================
# ✅ TUNNEL FILES
#   - PANEL (agent.py)      -> biasanya tunnel_panel.log / panel_url.txt
#   - noVNC VERIF (OTP)     -> tunnel_novnc.log / novnc_url.txt
#   NOTE: script ini akan kirim link VERIF (noVNC) saat OTP
# =========================================================

# (biarin tetap ada kalau kamu masih pakai lama)
TUNNEL_LOG = os.path.join(BASE_PATH, "tunnel.log")
TUNNEL_URL_FILE = os.path.join(BASE_PATH, "tunnel_url.txt")

# ✅ yang dipakai untuk VERIF (pisah dari panel)
TUNNEL_NOVNC_LOG = os.path.join(BASE_PATH, "tunnel_novnc.log")
TUNNEL_NOVNC_URL_FILE = os.path.join(BASE_PATH, "novnc_url.txt")

# =========================
# VNC LINK (UNTUK APP VNC)
# =========================
VNC_PORT = os.environ.get("VNC_PORT", "5900").strip()
VNC_HOST = os.environ.get("VNC_HOST", "").strip()
VNC_FILE = os.path.join(BASE_PATH, "vnc.txt")

# =========================================================
# 🔧 UTIL
# =========================================================

def now_str():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def get_public_ip():
    try:
        return requests.get("https://ifconfig.me", timeout=8).text.strip()
    except:
        return "Unknown IP"

def send_telegram_message(text):
    if not TG_BOT_TOKEN or "MASUKKAN" in TG_BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": text}
        requests.post(url, data=payload, timeout=15)
    except Exception as e:
        print(f"[⚠️] Telegram sendMessage error: {e}")

def send_telegram_photo(caption, image_path):
    if not TG_BOT_TOKEN or "MASUKKAN" in TG_BOT_TOKEN:
        return
    if not os.path.exists(image_path):
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
        with open(image_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": TG_CHAT_ID, "caption": caption}
            requests.post(url, files=files, data=data, timeout=25)
    except Exception as e:
        print(f"[⚠️] Telegram sendPhoto error: {e}")

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def save_mapping(full_path, profile_name):
    with open(MAPPING_FILE, "a", encoding="utf-8") as f:
        f.write(f"{full_path}|{profile_name}\n")

def create_first_run_sentinel(profile_path):
    ensure_dir(profile_path)
    with open(os.path.join(profile_path, "First Run"), "w", encoding="utf-8") as f:
        f.write("")

def random_name(n=10):
    chars = string.ascii_lowercase + string.digits
    return "app-" + "".join(random.choice(chars) for _ in range(n))

def take_screenshot(driver, name_prefix):
    ss_name = f"{name_prefix}_{now_str()}.png"
    ss_path = os.path.join(BASE_PATH, ss_name)
    try:
        driver.save_screenshot(ss_path)
        return ss_path
    except Exception as e:
        print(f"[⚠️] save_screenshot gagal: {e}")
        return None

def is_google_challenge(driver):
    try:
        u = driver.current_url.lower()
    except:
        return False
    keywords = ["challenge", "signin/v2/challenge", "accounts.google.com/signin/v2/challenge", "approval", "verify"]
    return any(k in u for k in keywords)

def wait_until_not_redirect_to_login(driver, wait, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        url = ""
        try:
            url = driver.current_url.lower()
        except:
            pass

        if ("studio.firebase.google.com" in url) or ("idx.google.com" in url) or ("firebase.google.com" in url):
            return True

        if is_google_challenge(driver):
            return False

        time.sleep(1)
    return False

def build_driver(profile_dir):
    chrome_options = Options()
    chrome_options.binary_location = CHROME_BINARY

    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--start-maximized")

    chrome_options.add_argument(f"--user-data-dir={profile_dir}")

    # 🔥 ANTI DETECTION
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # 🔥 HILANGKAN navigator.webdriver
    driver.execute_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        })
    """)

    driver.set_page_load_timeout(120)
    return driver

# =========================================================
# ✅ TUNNEL URL (KHUSUS VERIF / noVNC)
#   Ambil URL dari:
#     1) ENV NOVNC_TUNNEL_URL (opsional)
#     2) novnc_url.txt
#     3) parse tunnel_novnc.log
#   Fallback: kalau file novnc tidak ada, coba tunnel lama (tunnel_url/tunnel.log)
# =========================================================

def get_tunnel_url(timeout=25):
    # 1) ENV khusus noVNC
    env_url = os.environ.get("NOVNC_TUNNEL_URL", "").strip()
    if env_url.startswith("https://"):
        return env_url

    # 2) novnc_url.txt
    try:
        if os.path.exists(TUNNEL_NOVNC_URL_FILE):
            s = open(TUNNEL_NOVNC_URL_FILE, "r", encoding="utf-8", errors="ignore").read().strip()
            if s.startswith("https://"):
                return s
    except:
        pass

    # 3) parse tunnel_novnc.log
    import re
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if os.path.exists(TUNNEL_NOVNC_LOG):
                log = open(TUNNEL_NOVNC_LOG, "r", encoding="utf-8", errors="ignore").read()
                m = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", log)
                if m:
                    url = m.group(0)
                    try:
                        with open(TUNNEL_NOVNC_URL_FILE, "w", encoding="utf-8") as f:
                            f.write(url + "\n")
                    except:
                        pass
                    return url
        except:
            pass
        time.sleep(1)

    # ===== fallback ke sistem lama (biar ga ngerusak setup lama kamu) =====
    # env lama
    env_url2 = os.environ.get("TUNNEL_URL", "").strip()
    if env_url2.startswith("https://"):
        return env_url2

    # file lama
    try:
        if os.path.exists(TUNNEL_URL_FILE):
            s = open(TUNNEL_URL_FILE, "r", encoding="utf-8", errors="ignore").read().strip()
            if s.startswith("https://"):
                return s
    except:
        pass

    # log lama
    try:
        if os.path.exists(TUNNEL_LOG):
            log = open(TUNNEL_LOG, "r", encoding="utf-8", errors="ignore").read()
            m = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", log)
            if m:
                return m.group(0)
    except:
        pass

    return None

# =========================
# VNC LINK HELPERS
# =========================

def get_vnc_link():
    ensure_vnc_config()
    if VNC_HOST:
        return f"vnc://{VNC_HOST}:{VNC_PORT}"
    return None

def notify_vnc_verification(driver, label, email, reason="OTP/Verification terdeteksi"):
    # ✅ ambil URL tunnel KHUSUS noVNC (verif)
    tunnel_url = get_tunnel_url(timeout=25)
    ss = take_screenshot(driver, f"verify_{label}")

    msg = (
        f"⚠️ {reason}\n"
        f"Akun: {label}\n"
        f"Email: {email}\n"
    )

    if tunnel_url:
        msg += f"\n🖥️ noVNC (via Tunnel):\n{tunnel_url}\n"
    else:
        msg += (
            "\n❗ Tunnel URL belum kebaca.\n"
            "Pastikan cloudflared noVNC tunnel sudah jalan dan menulis ke tunnel_novnc.log / novnc_url.txt\n"
        )

    send_telegram_message(msg)
    if ss:
        send_telegram_photo(msg, ss)
    print(msg)

def detect_public_ip():
    ip = get_public_ip()
    if ip and ip != "Unknown IP":
        return ip.strip()
    return ""

def ensure_vnc_config():
    """
    Auto set VNC_HOST prioritas:
      1) ENV: VNC_HOST / VNC_PORT
      2) vnc.txt (kalau sudah diisi)
      3) AUTO detect public IP -> tulis ke vnc.txt
    """
    global VNC_HOST, VNC_PORT

    # refresh env
    VNC_HOST = os.environ.get("VNC_HOST", "").strip()
    VNC_PORT = os.environ.get("VNC_PORT", "5900").strip()

    # 1) ENV
    if VNC_HOST:
        return True

    # 2) vnc.txt
    try:
        if os.path.exists(VNC_FILE):
            s = open(VNC_FILE, "r", encoding="utf-8", errors="ignore").read().strip()
            if s:
                if s.startswith("vnc://"):
                    s = s.replace("vnc://", "", 1)

                if ":" in s:
                    host, port = s.split(":", 1)
                    host = host.strip()
                    port = port.strip() or VNC_PORT
                    if host and host.lower() != "your_vnc_host":
                        VNC_HOST = host
                        VNC_PORT = port
                        return True
                else:
                    host = s.strip()
                    if host and host.lower() != "your_vnc_host":
                        VNC_HOST = host
                        return True
    except:
        pass

    # 3) AUTO detect public ip
    auto_ip = detect_public_ip()
    if auto_ip:
        VNC_HOST = auto_ip
        try:
            with open(VNC_FILE, "w", encoding="utf-8") as f:
                f.write(f"{VNC_HOST}:{VNC_PORT}\n")
        except:
            pass
        return True

    # fallback template
    if not os.path.exists(VNC_FILE):
        try:
            with open(VNC_FILE, "w", encoding="utf-8") as f:
                f.write("YOUR_VNC_HOST:5900\n")
        except:
            pass

    return False

def wait_manual_verification(driver, label, email, timeout=600):
    notify_vnc_verification(
        driver, label, email,
        reason="OTP/Verification Google terdeteksi setelah input password"
    )

    t0 = time.time()
    last_ping = 0

    while time.time() - t0 < timeout:
        try:
            if not is_google_challenge(driver):
                return True
        except:
            pass

        if time.time() - last_ping > 60:
            last_ping = time.time()
            send_telegram_message(
                f"⏳ Masih menunggu verifikasi manual...\nAkun: {label}\nEmail: {email}\n"
                f"({int(time.time()-t0)}s/{timeout}s)"
            )

        time.sleep(2)

    ss = take_screenshot(driver, f"verify_timeout_{label}")
    send_telegram_message(f"⛔ Timeout verifikasi manual.\nAkun: {label}\nEmail: {email}")
    if ss:
        send_telegram_photo(f"⛔ Timeout verifikasi manual {label} ({email})", ss)
    return False

# =========================================================
# 🔐 LOGIN GOOGLE (SELENIUM)
# =========================================================

def google_login(driver, wait, email, password, label):
    # Paksa masuk halaman login Google yang benar (bukan hanya studio)
    login_url = "https://accounts.google.com/ServiceLogin?hl=en&continue=https%3A%2F%2Fstudio.firebase.google.com%2F"
    driver.get(login_url)
    time.sleep(3)

    # Debug biar kelihatan dia lagi di mana
    try:
        print(f"[DEBUG] URL: {driver.current_url}")
        print(f"[DEBUG] TITLE: {driver.title}")
    except:
        pass

    # Kalau ternyata sudah login, Google biasanya langsung lempar ke studio
    try:
        cur = driver.current_url.lower()
        if "accounts.google.com" not in cur:
            print("[✅] Sudah login (redirect ke studio).")
            return True
    except:
        pass

    # ==================
    # STEP 1: INPUT EMAIL
    # ==================
    try:
        # kadang ada tombol "Use another account"
        try:
            use_other = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(text(),'Use another account')]"))
            )
            use_other.click()
            time.sleep(1)
        except:
            pass

        email_box = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "identifierId"))
        )
        email_box.click()
        email_box.clear()
        email_box.send_keys(email)
        time.sleep(0.5)

        # Next (email)
        try:
            driver.find_element(By.ID, "identifierNext").click()
        except:
            email_box.send_keys(Keys.ENTER)

        print(f"[✅] Input email: {email}")

    except Exception as e:
        print(f"[❌] Gagal input email: {e}")
        ss = take_screenshot(driver, f"email_input_fail_{label}")
        if ss:
            send_telegram_photo(f"❌ Gagal input email {label} ({email})\n{e}", ss)
        return False

    time.sleep(2)

    # =====================
    # STEP 2: INPUT PASSWORD
    # =====================
    try:
        pass_box = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.NAME, "Passwd"))
        )
        pass_box.click()
        pass_box.clear()
        pass_box.send_keys(password)
        time.sleep(0.5)

        # Next (password)
        try:
            driver.find_element(By.ID, "passwordNext").click()
        except:
            pass_box.send_keys(Keys.ENTER)

        print("[✅] Input password & Next")

    except Exception as e:
        print(f"[❌] Gagal input password: {e}")
        ss = take_screenshot(driver, f"pass_input_fail_{label}")
        if ss:
            send_telegram_photo(f"❌ Gagal input password {label} ({email})\n{e}", ss)
        return False

    time.sleep(3)

    # ==========================
    # OTP / VERIFICATION HANDLING
    # ==========================
    if is_google_challenge(driver):
        ok_manual = wait_manual_verification(driver, label, email, timeout=900)
        if not ok_manual:
            return False

    # setelah manual/auto, pastikan masuk studio
    driver.get("https://studio.firebase.google.com/")
    time.sleep(5)

    ok = wait_until_not_redirect_to_login(driver, wait, timeout=120)
    if not ok and ("accounts.google.com" in driver.current_url.lower()):
        print("[❌] Login belum sukses (masih di accounts.google.com).")
        ss = take_screenshot(driver, f"login_stuck_{label}")
        if ss:
            send_telegram_photo(f"❌ Login stuck {label} ({email})", ss)
        return False

    print("[✅] Login selesai.")
    return True

# =========================================================
# 🚀 FIREBASE FLOW
# =========================================================

def open_firebase_and_accept(driver, wait):
    driver.get("https://studio.firebase.google.com/")
    time.sleep(15)

    try:
        driver.execute_script("document.getElementById('utos-checkbox').click();")
        print("[✅] Klik checkbox 'I accept'")
    except:
        print("[SKIP] Step: 'I accept' tidak ditemukan")

    try:
        wait.until(EC.element_to_be_clickable((By.XPATH,
            "/html/body/app-root/ui-loader/onboarding-wrapper/single-column-layout/div/div[2]/onboarding-welcome-v2/div/form/div[2]/button/span"))).click()
        print("[✅] Klik tombol 'Confirm'")
        time.sleep(1)
    except:
        print("[SKIP] Step: tombol 'Confirm' tidak ditemukan")

def create_express_project(driver, wait, project_no, label, email):
    try:
        driver.get("https://studio.firebase.google.com/new/express")
        time.sleep(5)

        input_field = wait.until(EC.presence_of_element_located((By.XPATH,
            "/html/body/app-root/ui-loader/new-template-app/single-column-layout/div/div/form/div[1]/input")))

        app_name = random_name()
        input_field.clear()
        input_field.send_keys(app_name)
        print(f"[✅] Isi nama app (project {project_no}): {app_name}")

        input_field.send_keys(Keys.ENTER)
        time.sleep(15)

        link = driver.current_url
        with open(HASIL_FILE, "a", encoding="utf-8") as f:
            f.write(link + "\n")

        print(f"[✅] Link tersalin dan disimpan (project {project_no}): {link}")
        time.sleep(3)
        return True

    except Exception as e:
        print(f"[❌] Gagal membuat project {project_no}: {e}")

        ss = take_screenshot(driver, f"error_project_{project_no}_{label}")
        caption = f"⚠️ ERROR membuat link project ke-{project_no}\nAkun: {label}\nEmail: {email}\nError: {e}"
        send_telegram_message(caption)
        if ss:
            send_telegram_photo(caption, ss)

        time.sleep(1)
        return False

def join_onboarding(driver, wait):
    try:
        driver.get("https://studio.firebase.google.com/")
        time.sleep(5)

        wait.until(EC.element_to_be_clickable((By.XPATH,
            "/html/body/app-root/ui-loader/firebase-studio-dashboard/idx-app-chrome/div/div[2]/div[1]/div[2]/devprofile-onboarding/div/div/div/div/button"))).click()
        print("[✅] Klik logo Join")
        time.sleep(10)

        input_field = wait.until(EC.presence_of_element_located((By.XPATH,
            "/html/body/app-root/wrapper-dialog/single-column-layout/div/div[2]/onboarding-dialog/div/form/div[1]/input")))

        ActionChains(driver).click(input_field).perform()
        ActionChains(driver).send_keys("Indonesia").perform()
        print("[✅] Ketik Indonesia")

        ActionChains(driver).send_keys(Keys.TAB).perform()
        print("[✅] Tekan TAB")

        ActionChains(driver).send_keys("A").perform()
        print("[✅] Tekan A")

        wait.until(EC.element_to_be_clickable((By.XPATH,
            "//html/body/app-root/wrapper-dialog/single-column-layout/div/div[2]/onboarding-dialog/div/div/div/button[2]/span"))).click()
        print("[✅] Klik Continue")
        time.sleep(5)

        return True

    except Exception as e:
        print(f"[ERROR] Exception occurred: {e}")
        print("[SKIP] Step failed")
        return False

def share_workspaces(driver, wait, label, email):
    driver.get("https://studio.firebase.google.com/")
    time.sleep(2)
    driver.get("https://studio.firebase.google.com/")
    time.sleep(5)

    # ✅ AUTO CREATE kalau belum ada
    if not os.path.exists(EMAILSHARE_FILE):
        try:
            with open(EMAILSHARE_FILE, "w", encoding="utf-8") as f:
                f.write("")
        except:
            pass

    if not os.path.exists(EMAILSHARE_FILE):
        send_telegram_message("⚠️ emailshare.txt tidak ditemukan. Step share dilewati.")
        print("[⚠️] emailshare.txt tidak ada, skip share.")
        return

    with open(EMAILSHARE_FILE, "r", encoding="utf-8") as f:
        share_email = f.read().strip()

    if not share_email:
        send_telegram_message("⚠️ emailshare.txt kosong. Step share dilewati.")
        print("[⚠️] emailshare.txt kosong, skip share.")
        return

    i = 1
    while i <= 10:
        retry = 0
        success = False

        while retry < 1 and not success:
            try:
                print(f"[🔄] Mulai proses workspace ke-{i}, percobaan ke-{retry + 1}")

                titik_xpath = f"/html/body/app-root/ui-loader/firebase-studio-dashboard/idx-app-chrome/div/div[2]/div[2]/div/your-workspaces/div[2]/workspace[{i}]/div/div/button/mat-icon"
                wait.until(EC.element_to_be_clickable((By.XPATH, titik_xpath))).click()
                print(f"[✅] Klik titik tiga workspace ke-{i}")
                time.sleep(1)

                try:
                    share_xpath = "//div[contains(@class, 'cdk-overlay-container')]//button[normalize-space()='Share']"
                    wait.until(EC.element_to_be_clickable((By.XPATH, share_xpath))).click()
                    print(f"[✅] Klik menu Share workspace ke-{i}")
                    time.sleep(1)
                except TimeoutException:
                    print(f"[⚠️] Tombol Share tidak muncul, mencoba klik Cancel")
                    cancel_xpath = "/html/body/div[6]/div[2]/div/mat-dialog-container/div/div/share-dialog/div/div[3]/button[2]"
                    try:
                        driver.find_element(By.XPATH, cancel_xpath).click()
                        print(f"[↩️] Klik tombol Cancel")
                    except Exception as e_cancel:
                        print(f"[❌] Gagal klik Cancel: {e_cancel}")
                    retry += 1
                    time.sleep(1)
                    continue

                add_xpath = "/html/body/div[6]/div/div[2]/mat-dialog-container/div/div/share-dialog/div/div[2]/input"
                add_input = wait.until(EC.element_to_be_clickable((By.XPATH, add_xpath)))
                add_input.click()

                ActionChains(driver).send_keys(share_email).perform()
                time.sleep(2)
                ActionChains(driver).send_keys(Keys.ENTER).perform()
                print(f"[✅] Masukkan email untuk workspace ke-{i}: {share_email}")
                time.sleep(2)

                confirm_xpath = "/html/body/div[6]/div/div[2]/mat-dialog-container/div/div/share-dialog/div/div[3]/div[2]/button/span"
                wait.until(EC.element_to_be_clickable((By.XPATH, confirm_xpath))).click()
                print(f"[✅] Klik tombol Share workspace ke-{i}")
                time.sleep(10)

                success = True
                i += 1

            except Exception as e:
                print(f"[❌] Gagal di workspace ke-{i}, percobaan ke-{retry + 1}: {e}")

                try:
                    cancel_btn_xpath = "/html/body/div[6]/div/div[2]/mat-dialog-container/div/div/share-dialog/div/div[3]/button[2]"
                    wait.until(EC.element_to_be_clickable((By.XPATH, cancel_btn_xpath))).click()
                    print(f"[✅] Klik tombol cancel")
                except Exception as cancel_e:
                    print(f"[⚠️] Tidak bisa klik tombol cancel: {cancel_e}")

                retry += 1
                time.sleep(2)

        if not success:
            print(f"[🔁] Semua percobaan gagal untuk workspace ke-{i}. Melanjutkan ke workspace berikutnya.")
            i += 1

    send_telegram_message(f"✅ Share workspace selesai untuk {label} ({email}).")

# =========================================================
# ✅ MAIN
# =========================================================

def main():
    VPS_IP = get_public_ip()

    if not os.path.exists(EMAIL_FILE):
        print("❌ email.txt tidak ditemukan")
        sys.exit(1)

    with open(EMAIL_FILE, "r", encoding="utf-8") as f:
        raw_lines = [line.strip() for line in f if line.strip()]

    if os.path.exists(MAPPING_FILE):
        os.remove(MAPPING_FILE)

    for i, line in enumerate(raw_lines, start=START_INDEX):
        if "|" not in line:
            print(f"⚠️ Format salah (skip): {line}")
            continue

        email, password = line.split("|", 1)
        email = email.strip()
        password = password.strip()

        label = f"{PROFILE_PREFIX}{i}"
        profile_dir = os.path.join(BASE_PROFILE_DIR, label)
        ensure_dir(profile_dir)

        if not os.path.exists(os.path.join(profile_dir, "First Run")):
            create_first_run_sentinel(profile_dir)

        save_mapping(profile_dir, label)

        print("\n" + "="*60)
        print(f"[👤] PROSES AKUN: {label} | {email}")
        print("="*60)

        send_telegram_message(
            f"🚀 Mulai proses akun\n"
            f"Label: {label}\n"
            f"Email: {email}\n"
            f"IP: {VPS_IP}"
        )

        driver = None
        try:
            driver = build_driver(profile_dir)
            wait = WebDriverWait(driver, 30)

            ok = google_login(driver, wait, email, password, label)
            if not ok:
                send_telegram_message(f"❌ Login gagal untuk {label} ({email}).")
                with open(AKUN_BERMASALAH, "a", encoding="utf-8") as f:
                    f.write(f"{email}|{password}  # Login gagal\n")
                try:
                    ss = take_screenshot(driver, f"login_fail_{label}")
                    if ss:
                        send_telegram_photo(f"❌ Login gagal {label} ({email})", ss)
                except:
                    pass
                try:
                    driver.quit()
                except:
                    pass
                continue

            open_firebase_and_accept(driver, wait)

            create_express_project(driver, wait, 1, label, email)
            create_express_project(driver, wait, 2, label, email)
            create_express_project(driver, wait, 3, label, email)

            join_onboarding(driver, wait)

            create_express_project(driver, wait, 4, label, email)
            create_express_project(driver, wait, 5, label, email)

            create_express_project(driver, wait, 6, label, email)
            time.sleep(65)

            create_express_project(driver, wait, 7, label, email)
            time.sleep(65)

            create_express_project(driver, wait, 8, label, email)
            time.sleep(65)

            create_express_project(driver, wait, 9, label, email)
            time.sleep(65)

            ok10 = create_express_project(driver, wait, 10, label, email)
            if ok10:
                send_telegram_message(f"✅ Akun {label} ({email}) berhasil membuat 10 project Firebase.")
                time.sleep(15)
            else:
                send_telegram_message(f"⚠️ Akun {label} ({email}) gagal di project ke-10.")

            share_workspaces(driver, wait, label, email)

            send_telegram_message(f"✅ PROSES SELESAI untuk {label} ({email}).")

        except Exception as e:
            print(f"[❌ ERROR GLOBAL] {label} {email}: {e}")
            send_telegram_message(f"❌ ERROR GLOBAL\nLabel: {label}\nEmail: {email}\nError: {e}")

            if driver:
                ss = take_screenshot(driver, f"global_error_{label}")
                if ss:
                    send_telegram_photo(f"❌ GLOBAL ERROR {label} ({email})\n{e}", ss)

            with open(AKUN_BERMASALAH, "a", encoding="utf-8") as f:
                f.write(f"{email}|{password}  # Error global\n")

        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            time.sleep(2)

    print("\n✅ Semua akun selesai diproses.")
    sys.exit(0)

if __name__ == "__main__":
    main()