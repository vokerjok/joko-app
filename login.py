import os
import time
import traceback
from pathlib import Path
from datetime import datetime
from multiprocessing import Process, Queue

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC



# =========================
# PATHS (NON-ROOT DEFAULT)
# =========================
BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# email.txt format:
# akun1@gmail.com|pass1
# akun2@gmail.com|pass2
EMAIL_FILE = os.path.join(BASE_PATH, "email.txt")

# optional: ditulis untuk kompatibilitas (agent / mapping)
MAPPING_FILE = os.path.join(BASE_PATH, "mapping_profil.txt")

# ✅ NON-ROOT profiles root: default $HOME/chrome_profiles
PROFILES_ROOT = os.environ.get("PROFILES_ROOT") or os.path.join(BASE_PATH, "chrome_profiles")
PROFILES_ROOT = os.path.abspath(PROFILES_ROOT)

# snapshots
SNAP_DIR = os.environ.get("SNAP_DIR", os.path.join(BASE_PATH, "snapshots"))
Path(SNAP_DIR).mkdir(parents=True, exist_ok=True)

# =========================
# SELENIUM / CHROME CONFIG
# =========================
# Docker recommended:
# CHROME_BINARY=/usr/bin/chromium
# CHROMEDRIVER_PATH=/usr/bin/chromedriver
CHROME_BINARY = os.environ.get("CHROME_BINARY", "").strip()
CHROMEDRIVER_PATH = os.environ.get("CHROMEDRIVER_PATH", "").strip()

HEADLESS = os.environ.get("HEADLESS", "0").strip() == "1"

# kalau kamu mau script stop setelah sekian menit per akun
LOGIN_MAX_MIN = os.environ.get("LOGIN_MAX_MIN", "").strip()
LOGIN_MAX_SEC = int(LOGIN_MAX_MIN) * 60 if LOGIN_MAX_MIN.isdigit() else None

POLL_SEC = float(os.environ.get("POLL_SEC", "2"))

# Telegram (optional)
TG_TOKEN = os.environ.get("TG_TOKEN", "8333206393:AAG8Z76SSbgAEAC1a3oPT8XhAF9t_rDOq3A").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "-1003532458425").strip()

# ✅ NEW: max parallel logins (default 5)
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "5").strip() or "5")


# =========================
# TELEGRAM HELPERS
# =========================
def tg_enabled() -> bool:
    return bool(TG_TOKEN and TG_CHAT_ID)

def tg_send_text(text: str):
    if not tg_enabled():
        return False
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=30)
        return r.ok
    except Exception:
        return False

def tg_send_photo(caption: str, photo_path: str):
    if not tg_enabled():
        return False
    if not photo_path or not os.path.exists(photo_path):
        return tg_send_text(caption)

    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
            r = requests.post(url, data=data, files=files, timeout=60)
        return r.ok
    except Exception:
        return tg_send_text(caption)


# =========================
# UTIL
# =========================
def now_tag():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def mask_email(email: str) -> str:
    try:
        name, domain = email.split("@", 1)
        if len(name) <= 2:
            return f"{name[0]}***@{domain}"
        return f"{name[:2]}***@{domain}"
    except Exception:
        return email

def snap_path(account_idx: int, kind: str):
    Path(SNAP_DIR).mkdir(parents=True, exist_ok=True)
    return os.path.join(SNAP_DIR, f"acc{account_idx}_{kind}_{now_tag()}.png")

def capture_screenshot(driver, path: str) -> bool:
    try:
        Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(path)
        return True
    except Exception:
        return False

def read_accounts(path: str):
    p = Path(path)
    if not p.exists():
        # auto create (biar panel gampang)
        p.write_text("", encoding="utf-8")

    accounts = []
    for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            continue
        email, pwd = line.split("|", 1)
        email = email.strip()
        pwd = pwd.strip()
        if email and pwd:
            accounts.append((email, pwd))
    return accounts


# =========================
# CHROME DRIVER
# =========================
def build_driver(user_data_dir: str):
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    opts = webdriver.ChromeOptions()

    # ✅ KUNCI: folder clone profile per akun (joko1, joko2, ...)
    opts.add_argument(f"--user-data-dir={user_data_dir}")

    # ✅ cocok dengan loop.py: dia pakai profile-directory Default
    opts.add_argument("--profile-directory=Default")

    # stability
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--window-size=1280,720")

    # ✅ anti sync / chrome sign-in prompt (lebih stabil, mengurangi prompt sync)
    opts.add_argument("--disable-sync")
    opts.add_argument("--disable-features=SyncPromo,SigninPromo")

    # ✅ prefs tambahan (reduce prompt & noise)
    opts.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
        "sync_promo.show_on_first_run": False,
        "signin.allowed": False,
    })

    # anti detection (basic)
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    if CHROME_BINARY:
        opts.binary_location = CHROME_BINARY

    if HEADLESS:
        # catatan: google login sering rewel kalau headless
        opts.add_argument("--headless=new")


    # ==============================
    # 🔥 EXTRA STABILITY SETTINGS (ADDED)
    # ==============================
    opts.add_argument("--test-type")
    opts.add_argument("--simulate-outdated-no-au=Tue, 31 Dec 2099 23:59:59 GMT")
    opts.add_argument("--disable-component-update")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--remote-allow-origins=*")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--window-size=500,500")
    opts.add_argument("--disable-extensions")
    opts.add_experimental_option(
        "excludeSwitches",
        ["enable-automation", "enable-logging"]
    )
    opts.add_experimental_option(
        "prefs",
        {
            "profile.default_content_setting_values.notifications": 2,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.exit_type": "Normal",
            "profile.exited_cleanly": True
        }
    )

    # init driver
    if CHROMEDRIVER_PATH:
        service = ChromeService(CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=opts)
    else:
        driver = webdriver.Chrome(options=opts)

    driver.set_page_load_timeout(120)

    # hide webdriver flag
    try:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception:
        pass

    return driver


# =========================
# DETECT STATES
# =========================
def is_login_success(driver) -> bool:
    try:
        url = (driver.current_url or "").lower()
        if "myaccount.google.com" in url:
            return True
        if "mail.google.com" in url:
            return True
        # kadang sudah login tapi masih di accounts.google.com
        if "accounts.google.com" in url and "challenge" not in url and "/signin" not in url and "select" not in url:
            return True

        candidates = [
            (By.CSS_SELECTOR, "img[alt*='Google Account']"),
            (By.CSS_SELECTOR, "a[aria-label*='Google Account']"),
            (By.CSS_SELECTOR, "button[aria-label*='Google Account']"),
            (By.CSS_SELECTOR, "[aria-label*='Akun Google']"),
            (By.CSS_SELECTOR, "[aria-label*='Google Account']"),
        ]
        for by, sel in candidates:
            if driver.find_elements(by, sel):
                return True
    except Exception:
        pass
    return False


def is_otp_challenge(driver) -> bool:
    try:
        url = (driver.current_url or "").lower()
        if "accounts.google.com" in url and "challenge" in url:
            return True

        # input otp
        otp_candidates = [
            (By.CSS_SELECTOR, "input[type='tel']"),
            (By.CSS_SELECTOR, "input[type='number']"),
            (By.CSS_SELECTOR, "input[name='totpPin']"),
            (By.CSS_SELECTOR, "input[id*='totp']"),
        ]
        for by, sel in otp_candidates:
            if driver.find_elements(by, sel):
                return True

        page = (driver.page_source or "").lower()
        keywords = [
            "verify it's you", "verify it’s you",
            "2-step verification",
            "enter the code",
            "verification code",
            "kode verifikasi",
            "verifikasi",
            "otp",
        ]
        return any(k in page for k in keywords)
    except Exception:
        return False


def wait_until_done(driver, account_idx: int, email: str):
    otp_notified = False
    success_notified = False
    start = time.time()

    while True:
        # stop kalau chrome ditutup user
        try:
            if not driver.window_handles:
                return False
        except Exception:
            return False

        if is_login_success(driver):
            if not success_notified:
                sp = snap_path(account_idx, "SUCCESS")
                capture_screenshot(driver, sp)

                tg_send_photo(
                    caption=(
                        f"✅ <b>LOGIN SUKSES</b>\n"
                        f"Akun: <code>{mask_email(email)}</code>\n"
                        f"Time: <code>{now_tag()}</code>"
                    ),
                    photo_path=sp
                )

                success_notified = True

            # ===============================
            # 🔥 AUTO MASUK FIREBASE STUDIO
            # ===============================
            try:
                driver.get("https://studio.firebase.google.com/")
                time.sleep(15)

                sp_fb = snap_path(account_idx, "FIREBASE_STUDIO")
                capture_screenshot(driver, sp_fb)

                tg_send_photo(
                    caption=(
                        f"🚀 <b>MASUK FIREBASE STUDIO</b>\n"
                        f"Akun: <code>{mask_email(email)}</code>\n"
                        f"Status: OTP selesai → redirect otomatis\n"
                        f"Time: <code>{now_tag()}</code>"
                    ),
                    photo_path=sp_fb
                )

            except Exception as e:
                tg_send_text(
                    f"⚠️ Gagal masuk Firebase Studio\n"
                    f"Akun: {mask_email(email)}\n"
                    f"Err: {str(e)[:150]}"
                )

            return True

        if is_otp_challenge(driver) and not otp_notified:
            sp = snap_path(account_idx, "OTP")
            capture_screenshot(driver, sp)
            tg_send_photo(
                caption=(
                    f"🔐 <b>OTP / VERIFIKASI TERDETEKSI</b>\n"
                    f"Akun: <code>{mask_email(email)}</code>\n"
                    f"Action: Selesaikan OTP di Chrome\n"
                    f"Time: <code>{now_tag()}</code>"
                ),
                photo_path=sp
            )
            otp_notified = True

        if LOGIN_MAX_SEC is not None and (time.time() - start) > LOGIN_MAX_SEC:
            sp = snap_path(account_idx, "TIMEOUT")
            capture_screenshot(driver, sp)
            tg_send_photo(
                caption=(
                    f"⏰ <b>TIMEOUT MENUNGGU LOGIN</b>\n"
                    f"Akun: <code>{mask_email(email)}</code>\n"
                    f"Time: <code>{now_tag()}</code>"
                ),
                photo_path=sp
            )
            return False

        time.sleep(POLL_SEC)


# =========================
# LOGIN FLOW
# =========================
def google_login_flow(driver, account_idx: int, email: str, password: str):
    wait = WebDriverWait(driver, 60)

    # buka login
    driver.get("https://accounts.google.com/signin/v2/identifier")
    time.sleep(5)

    # input email
    try:
        email_box = wait.until(EC.element_to_be_clickable((By.ID, "identifierId")))
        email_box.click()
        email_box.clear()
        email_box.send_keys(email)

        try:
            driver.find_element(By.ID, "identifierNext").click()
        except Exception:
            email_box.send_keys(Keys.ENTER)

        print(f"[✅] Email diketik: {email}")

        # 📸 screenshot setelah ketik EMAIL
        sp_email = snap_path(account_idx, "EMAIL_TYPED")
        capture_screenshot(driver, sp_email)
        tg_send_photo(
            caption=(
                f"✉️ <b>EMAIL DIKETIK</b>\n"
                f"#email: <code>{account_idx}</code>\n"
                f"#clone: <code>joko{account_idx}</code>\n"
                f"Akun: <code>{mask_email(email)}</code>\n"
                f"Time: <code>{now_tag()}</code>"
            ),
            photo_path=sp_email
        )

    except Exception as e:
        sp = snap_path(account_idx, "EMAIL_FAIL")
        capture_screenshot(driver, sp)
        tg_send_photo(
            caption=f"❌ EMAIL FAIL\nAkun: <code>{mask_email(email)}</code>\nErr: <code>{str(e)[:200]}</code>",
            photo_path=sp
        )
        return False

    time.sleep(5)


    # 📸 screenshot sebelum nunggu field PASSWORD (buat debug kalau nyangkut setelah email)
    try:
        sp_before = snap_path(account_idx, "BEFORE_PASSWORD_WAIT")
        capture_screenshot(driver, sp_before)
        tg_send_photo(
            caption=(
                f"⏳ <b>BEFORE PASSWORD WAIT</b>\n"
                f"#email: <code>{account_idx}</code>\n"
                f"#clone: <code>joko{account_idx}</code>\n"
                f"Akun: <code>{mask_email(email)}</code>\n"
                f"Time: <code>{now_tag()}</code>"
            ),
            photo_path=sp_before
        )
    except Exception:
        pass

    # input password
    try:
        pwd_box = wait.until(EC.element_to_be_clickable((By.NAME, "Passwd")))
        pwd_box.click()
        pwd_box.clear()
        pwd_box.send_keys(password)

        try:
            driver.find_element(By.ID, "passwordNext").click()
        except Exception:
            pwd_box.send_keys(Keys.ENTER)

        print("[✅] Password diketik & submit")

        # 📸 screenshot setelah ketik PASSWORD (sebelum submit)
        sp_pass = snap_path(account_idx, "PASS_TYPED")
        capture_screenshot(driver, sp_pass)
        tg_send_photo(
            caption=(
                f"🔑 <b>PASSWORD DIKETIK</b>\n"
                f"#email: <code>{account_idx}</code>\n"
                f"#clone: <code>joko{account_idx}</code>\n"
                f"Akun: <code>{mask_email(email)}</code>\n"
                f"Time: <code>{now_tag()}</code>"
            ),
            photo_path=sp_pass
        )
        
        time.sleep(5)
        
    except Exception as e:
        sp = snap_path(account_idx, "PASS_FAIL")
        capture_screenshot(driver, sp)
        tg_send_photo(
            caption=f"❌ PASS FAIL\nAkun: <code>{mask_email(email)}</code>\nErr: <code>{str(e)[:200]}</code>",
            photo_path=sp
        )
        return False

    # screenshot setelah password
    sp = snap_path(account_idx, "AFTER_PASSWORD")
    capture_screenshot(driver, sp)
    tg_send_photo(
        caption=(
            f"📸 <b>SETELAH SUBMIT PASSWORD</b>\n"
            f"Akun: <code>{mask_email(email)}</code>\n"
            f"Time: <code>{now_tag()}</code>\n"
            f"Note: Jika muncul OTP, akan dikirim notif terpisah."
        ),
        photo_path=sp
    )

    print("[⏳] Menunggu OTP/verifikasi manual atau login sukses...")
    return wait_until_done(driver, account_idx, email)


# =========================
# MAPPING FILE (compat)
# =========================
def write_mapping_file(mapping_path: str, accounts_count: int):
    """
    Ditulis untuk kompatibilitas agent/skrip lain.
    Format:
        /home/app/chrome_profiles/joko1|joko1
        /home/app/chrome_profiles/joko2|joko2
    """
    tmp = mapping_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for idx in range(1, accounts_count + 1):
            name = f"joko{idx}"
            user_data_dir = os.path.join(PROFILES_ROOT, name)
            f.write(f"{user_data_dir}|{name}\n")
    os.replace(tmp, mapping_path)


# =========================
# WORKER (parallel)
# =========================
def _run_one_account(idx: int, email: str, pwd: str):
    profile_name = f"joko{idx}"
    user_data_dir = os.path.join(PROFILES_ROOT, profile_name)

    print("=" * 70)
    print(f"[▶] AKUN #{idx} | {email}")
    print(f"[i] profile folder: {user_data_dir}")
    print(f"[i] loop.py akan scan: {profile_name} ✅")

    driver = None
    try:
        driver = build_driver(user_data_dir)
        ok = google_login_flow(driver, idx, email, pwd)

        # close setelah selesai
        try:
            driver.quit()
        except Exception:
            pass

        if ok:
            print(f"[✅] DONE #{idx} ({profile_name})")
        else:
            print(f"[⚠️] NOT OK #{idx} ({profile_name}) - cek OTP/verif")

        return (idx, email, ok, "")

    except Exception as e:
        print(f"[❌] ERROR akun #{idx}: {type(e).__name__}: {e}")
        traceback.print_exc()

        sp = ""
        if driver:
            sp = snap_path(idx, "ERROR")
            capture_screenshot(driver, sp)

        tg_send_photo(
            caption=(
                f"❌ <b>ERROR FATAL</b>\n"
                f"Akun: <code>{mask_email(email)}</code>\n"
                f"Profile: <code>{profile_name}</code>\n"
                f"Err: <code>{str(e)[:240]}</code>\n"
                f"Time: <code>{now_tag()}</code>"
            ),
            photo_path=sp
        )

        if driver:
            try:
                driver.quit()
            except Exception:
                pass

        return (idx, email, False, f"{type(e).__name__}: {e}")


def _proc_wrapper(q: Queue, idx: int, email: str, pwd: str):
    try:
        res = _run_one_account(idx, email, pwd)
        q.put(res)
    except Exception as e:
        q.put((idx, email, False, f"{type(e).__name__}: {e}"))


# =========================
# MAIN
# =========================
def main():
    accounts = read_accounts(EMAIL_FILE)
    if not accounts:
        print(f"[❌] Tidak ada akun valid di {EMAIL_FILE}")
        print("Format harus: email|password (1 per baris)")
        return

    # ✅ tulis mapping untuk kompatibilitas (walau loop.py scan folder langsung)
    try:
        write_mapping_file(MAPPING_FILE, len(accounts))
        print(f"[✅] mapping_profil.txt updated: {MAPPING_FILE}")
    except Exception as e:
        print(f"[WARN] gagal tulis mapping_profil.txt: {e}")

    if tg_enabled():
        tg_send_text(
            "🚀 <b>LOGIN START</b>\n"
            f"Total akun: <code>{len(accounts)}</code>\n"
            f"PROFILES_ROOT: <code>{PROFILES_ROOT}</code>\n"
            f"HEADLESS: <code>{int(HEADLESS)}</code>\n"
            f"MODE: <code>PARALLEL ({MAX_PARALLEL} sekaligus)</code>"
        )

    # ✅ PARALLEL RUN (default 5 sekaligus)
    results = []
    q = Queue()

    procs = []
    for idx, (email, pwd) in enumerate(accounts, start=1):
        p = Process(target=_proc_wrapper, args=(q, idx, email, pwd))
        p.start()
        procs.append(p)

        # batasi max parallel
        if len(procs) >= MAX_PARALLEL:
            for pp in procs:
                pp.join()
            procs = []

    # join sisa
    for pp in procs:
        pp.join()

    # ambil hasil (sebanyak jumlah akun)
    for _ in range(len(accounts)):
        try:
            results.append(q.get(timeout=5))
        except Exception:
            # kalau ada yang gak sempat masuk queue
            pass

    if tg_enabled():
        ok_count = sum(1 for r in results if r and len(r) >= 3 and r[2] is True)
        tg_send_text(
            "✅ <b>LOGIN FINISH</b>\n"
            f"OK: <code>{ok_count}</code> / Total: <code>{len(accounts)}</code>\n"
            f"Semua akun sudah diproses secara PARALLEL ({MAX_PARALLEL})."
        )

    print("[DONE] semua akun selesai.")


if __name__ == "__main__":
    main()