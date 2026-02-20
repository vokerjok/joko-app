from multiprocessing import Process
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
import time
from datetime import datetime
import requests
import json
import shutil
import glob

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
PROFILES_ROOT = os.environ.get("PROFILES_ROOT") or os.path.join(BASE_PATH, "chrome_profiles")
PROFILES_ROOT = os.path.abspath(PROFILES_ROOT)
os.makedirs(PROFILES_ROOT, exist_ok=True)

# email.txt (optional untuk label saja)
EMAIL_FILE = os.path.join(BASE_PATH, "email.txt")

# ✅ status file untuk panel (dibaca agent.py)
STATUS_FILE = os.path.join(BASE_PATH, "loop_status.json")

# ✅ loop log file (untuk truncate tiap 5 menit)
LOOP_LOG_FILE = os.path.join(BASE_PATH, "loop_log.txt")

# Delay & timing
PRE_OPEN_DELAY = int(os.environ.get("PRE_OPEN_DELAY", "5"))          # delay sebelum get(link)
START_PROFILE_DELAY = int(os.environ.get("START_PROFILE_DELAY", "25"))
SLEEP_SEBELUM_AKSI = int(os.environ.get("SLEEP_SEBELUM_AKSI", "5"))
SLEEP_SESUDAH_AKSI = int(os.environ.get("SLEEP_SESUDAH_AKSI", "5"))
SLEEP_JIKA_ERROR = int(os.environ.get("SLEEP_JIKA_ERROR", "3"))

# ✅ NEW: delay setelah selesai 1 putaran link milik profile, lalu ulang dari awal
SLEEP_AFTER_FULL_ROUND = int(os.environ.get("SLEEP_AFTER_FULL_ROUND", "2"))

# Default paling aman 1 (naikin kalau server kuat)
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "20"))

# Chrome profile directory di dalam user-data-dir (biasanya Default)
PROFILE_DIR = os.environ.get("PROFILE_DIR", "Default")

# Telegram (optional)
TG_TOKEN = os.environ.get("TG_TOKEN", "8333206393:AAG8Z76SSbgAEAC1a3oPT8XhAF9t_rDOq3A").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "-1003532458425").strip()

# ✅ LOG TRUNCATE tiap 5 menit
LOG_TRUNCATE_SECONDS = 300  # 5 menit


# ======================
# TELEGRAM HELPERS
# ======================
def tg_enabled():
    return bool(TG_TOKEN and TG_CHAT_ID)

def tg_send_message(text: str):
    if not tg_enabled():
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": text}, timeout=15)
    except:
        pass

def tg_send_photo(photo_path: str, caption: str):
    if not tg_enabled():
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption}, files={"photo": f}, timeout=30)
    except:
        pass


# ======================
# STATUS (per profile)
# ======================
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _safe_read_json(path, default=None):
    if default is None:
        default = {}
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception:
        return default

def _safe_write_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass

def update_status(profile_name: str, **kwargs):
    data = _safe_read_json(STATUS_FILE, default={})
    if not isinstance(data, dict):
        data = {}
    st = data.get(profile_name) if isinstance(data.get(profile_name), dict) else {}
    st.update(kwargs)
    st["last_update"] = _now()
    data[profile_name] = st
    _safe_write_json(STATUS_FILE, data)


# ======================
# FILE HELPERS
# ======================
def read_file_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return [line.strip() for line in f if line.strip()]

def read_emails(path):
    """
    email.txt format:
    akun1@gmail.com|pass
    akun2@gmail.com|pass
    return list of email only (order)
    """
    emails = []
    for line in read_file_lines(path):
        if "|" in line:
            emails.append(line.split("|", 1)[0].strip())
        else:
            emails.append(line.strip())
    return emails


# ======================
# PROFILE SCAN (jokoX folders)
# ======================
def scan_joko_folders(profiles_root: str):
    out = []
    if not os.path.isdir(profiles_root):
        return out

    found = []
    for name in os.listdir(profiles_root):
        full = os.path.join(profiles_root, name)
        if not os.path.isdir(full):
            continue
        low = name.lower()
        if not low.startswith("joko"):
            continue
        num = name[4:]
        if num.isdigit():
            found.append((int(num), name, full))

    found.sort(key=lambda x: x[0])
    for _, name, full in found:
        out.append({
            "name": name,
            "user_data_dir": full,
            "profile_dir": PROFILE_DIR,
        })
    return out


# ======================
# LOCK (anti profile in use)
# ======================
def lock_path_for_user_data_dir(user_data_dir: str) -> str:
    safe = user_data_dir.replace("/", "_").replace(" ", "_")
    return os.path.join(BASE_PATH, f".lock_{safe}.pid")

def acquire_profile_lock(user_data_dir: str) -> bool:
    lp = lock_path_for_user_data_dir(user_data_dir)
    try:
        if os.path.exists(lp):
            try:
                old_pid = int(open(lp, "r").read().strip() or "0")
            except:
                old_pid = 0
            if old_pid > 0:
                try:
                    os.kill(old_pid, 0)
                    return False
                except:
                    pass
        with open(lp, "w") as f:
            f.write(str(os.getpid()))
        return True
    except:
        return False

def release_profile_lock(user_data_dir: str):
    lp = lock_path_for_user_data_dir(user_data_dir)
    try:
        if os.path.exists(lp):
            os.remove(lp)
    except:
        pass


# ======================
# CHROME OPTIONS
# ======================
def get_options(user_data_dir: str, profile_dir: str):
    options = webdriver.ChromeOptions()

    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument(f"--profile-directory={profile_dir or 'Default'}")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--window-size=900,720")

    options.add_argument("--restore-last-session")

    # ✅ anti sync / chrome sign-in prompt
    options.add_argument("--disable-sync")
    options.add_argument("--disable-features=SyncPromo,SigninPromo")

    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option(
        "prefs",
        {
            "profile.default_content_setting_values.notifications": 2,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,

            # ✅ reduce sync/signin prompts
            "sync_promo.show_on_first_run": False,
            "signin.allowed": False,
        },
    )

    # ==============================
    # 🔥 EXTRA STABILITY SETTINGS (ADDED)
    # ==============================
    options.add_argument("--test-type")
    options.add_argument("--simulate-outdated-no-au=Tue, 31 Dec 2099 23:59:59 GMT")
    options.add_argument("--disable-component-update")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--window-size=500,500")
    options.add_argument("--disable-extensions")
    options.add_experimental_option(
        "excludeSwitches",
        ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option(
        "prefs",
        {
            "profile.default_content_setting_values.notifications": 2,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.exit_type": "Normal",
            "profile.exited_cleanly": True
        }
    )

    return options


# ======================
# SCREENSHOT
# ======================
def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def save_screenshot(driver, profile_name, prefix="SHOT"):
    ensure_dir(os.path.join(BASE_PATH, "screenshots"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(BASE_PATH, "screenshots", f"{prefix}_{profile_name}_{ts}.png")
    try:
        driver.save_screenshot(out)
        return out
    except:
        return ""

def save_fail_screenshot(driver, profile_name, prefix="FAIL"):
    return save_screenshot(driver, profile_name, prefix=prefix)


# ======================
# LOOP LOG TRUNCATE
# ======================
def truncate_loop_log_if_needed(state):
    """
    state: dict with 'last_trunc'
    """
    try:
        now = time.time()
        last = state.get("last_trunc", 0)
        if now - last >= LOG_TRUNCATE_SECONDS:
            # truncate file
            try:
                with open(LOOP_LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("")
            except:
                pass
            state["last_trunc"] = now
    except:
        pass


# ======================
# ✅ RECOVERY HELPERS (NEW)
# ======================
def _rm_path(p: str):
    try:
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.isfile(p):
            os.remove(p)
    except:
        pass

def cleanup_profile_cache(user_data_dir: str):
    """
    Hapus cache Chrome di user_data_dir agar clone yang crash bisa bersih.
    Tetap aman: tidak hapus folder utama profile, hanya cache/temp umum.
    """
    try:
        candidates = [
            os.path.join(user_data_dir, "Default", "Cache"),
            os.path.join(user_data_dir, "Default", "Code Cache"),
            os.path.join(user_data_dir, "Default", "GPUCache"),
            os.path.join(user_data_dir, "Default", "Service Worker", "CacheStorage"),
            os.path.join(user_data_dir, "Default", "Service Worker", "ScriptCache"),
            os.path.join(user_data_dir, "Default", "Storage", "ext"),
            os.path.join(user_data_dir, "Default", "Local Storage"),
            os.path.join(user_data_dir, "Default", "Session Storage"),
            os.path.join(user_data_dir, "Default", "Sessions"),
            os.path.join(user_data_dir, "Default", "WebStorage"),
            os.path.join(user_data_dir, "Crashpad"),
        ]
        for p in candidates:
            _rm_path(p)

        # kadang cache ada di root
        for p in ["Cache", "Code Cache", "GPUCache"]:
            _rm_path(os.path.join(user_data_dir, p))

        # buang file crash/log temp yang kadang bikin hang
        for pattern in [
            os.path.join(user_data_dir, "*.tmp"),
            os.path.join(user_data_dir, "*.log"),
        ]:
            for fp in glob.glob(pattern):
                _rm_path(fp)

        # bersihin tmp chrome yang sering ngunci
        _rm_path("/tmp/.com.google.Chrome*")
        _rm_path("/tmp/.org.chromium.Chromium*")
    except:
        pass


# ======================
# LINK WORK
# ======================
def process_single_link(driver, profile_name, email, link, idx, total, round_num):
    # update status (start open link)
    update_status(
        profile_name,
        state="RUNNING",
        round_num=round_num,
        link_idx=idx,
        link_total=total,
        current_link=link,
        last_error=""
    )

    # ✅ notif + screenshot tiap buka link (sesuai request)
    if tg_enabled():
        tg_send_message(
            "🌐 OPEN LINK\n"
            f"Profile: {profile_name}\n"
            f"Email: {email}\n"
            f"Round: {round_num}\n"
            f"Index: {idx}/{total}\n"
            f"Link: {link}"
        )

    try:
        time.sleep(PRE_OPEN_DELAY)

        driver.get(link)
        wait = WebDriverWait(driver, 12)

        # klik trust / open workspace kalau ada
        try:
            trust = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), 'I trust the owner')]")))
            trust.click()
        except:
            pass

        # ============================
        # 🔥 OPEN WORKSPACE (NOTIF kalau error)
        # ============================
        try:
            open_ws = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Open Workspace')]")))
            try:
                open_ws.click()
            except Exception as e_click:
                shot = save_fail_screenshot(driver, profile_name, prefix="OPEN_WORKSPACE_FAIL")
                caption = (
                    "❌ OPEN WORKSPACE CLICK ERROR\n"
                    f"Profile: {profile_name}\n"
                    f"Email: {email}\n"
                    f"Round: {round_num}\n"
                    f"Index: {idx}/{total}\n"
                    f"Link: {link}\n"
                    f"Error: {type(e_click).__name__}: {str(e_click)[:160]}"
                )
                if shot:
                    tg_send_photo(shot, caption)
                else:
                    tg_send_message(caption)

                update_status(profile_name, state="ERROR_OPEN_WORKSPACE", last_error=caption[:260])
        except Exception:
            pass

        # tunggu iframe IDE (kalau link Firebase Studio)
        try:
            wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "iframe.the-iframe.is-loaded[src*='ide-start']")))
        except:
            pass

        time.sleep(SLEEP_SEBELUM_AKSI)

        try:
            driver.find_element(By.TAG_NAME, "body").click()
        except:
            pass

        try:
            actions = ActionChains(driver)
            actions.key_down(Keys.CONTROL).send_keys("`").key_up(Keys.CONTROL).perform()
        except:
            pass

        time.sleep(SLEEP_SESUDAH_AKSI)

        # ✅ kirim screenshot sukses buka link
        if tg_enabled():
            shot_ok = save_screenshot(driver, profile_name, prefix="OPEN_OK")
            if shot_ok:
                tg_send_photo(
                    shot_ok,
                    f"✅ LINK OPENED\nProfile: {profile_name}\nEmail: {email}\nIndex: {idx}/{total}\nLink: {link}"
                )

        update_status(profile_name, state="RUNNING", last_error="")
        return True, ""

    except Exception as e:
        err = f"{type(e).__name__}: {str(e)}"
        shot = save_fail_screenshot(driver, profile_name, prefix="FAIL")

        caption = (
            "❌ LINK GAGAL DIBUKA\n"
            f"Profile: {profile_name}\n"
            f"Email: {email}\n"
            f"Round: {round_num}\n"
            f"Index: {idx}/{total}\n"
            f"Link: {link}\n"
            f"Error: {err}"
        )
        if shot:
            tg_send_photo(shot, caption)
        else:
            tg_send_message(caption)

        update_status(profile_name, state="ERROR", last_error=err[:260])
        time.sleep(SLEEP_JIKA_ERROR)
        return False, err


# ======================
# WORKER (1 profile = 1 chrome, NEVER CLOSE, LOOP BACK)
# ======================
def worker(profile_name, email, user_data_dir, profile_dir, total_slots, group_counts):
    if not acquire_profile_lock(user_data_dir):
        msg = f"⚠️ SKIP: profile sedang dipakai proses lain: {profile_name}\nuser_data_dir={user_data_dir}"
        print(msg)
        if tg_enabled():
            tg_send_message(msg)
        update_status(profile_name, state="SKIP_LOCK", last_error="profile lock aktif")
        return

    driver = None
    try:
        # ✅ ambil nomor profile dari nama (jokoX -> X)
        prof_num = 0
        try:
            low = (profile_name or "").lower()
            if low.startswith("joko"):
                tail = low[4:]
                if tail.isdigit():
                    prof_num = int(tail)
        except Exception:
            prof_num = 0

        # ==============================
        # ✅ Mapping file link per 10 clone:
        # 1-10 -> joko1.txt
        # 11-20 -> joko2.txt
        # dst...
        # ==============================
        GROUP_SIZE = 10
        group_idx = ((prof_num - 1) // GROUP_SIZE) + 1 if prof_num > 0 else 1
        local_num = ((prof_num - 1) % GROUP_SIZE) + 1 if prof_num > 0 else 1  # 1..10
        shared_link_file = os.path.join(BASE_PATH, f"joko{group_idx}.txt")

        # ✅ group_slots = jumlah clone yg benar-benar ada di group itu (misal cuma 5 clone -> bagi 5)
        group_slots = int(group_counts.get(group_idx, GROUP_SIZE) or GROUP_SIZE)
        if group_slots <= 0:
            group_slots = 1

        # state untuk truncate log
        log_state = {"last_trunc": 0}

        update_status(profile_name, state="RUNNING", round_num=0, link_idx=0, link_total=0, current_link="", last_error="")

        # =========================================================
        # ✅ AUTO-RECOVERY LOOP (NEW):
        # kalau driver crash / error berat -> close, hapus cache, start lagi
        # =========================================================
        round_num = 0
        while True:
            try:
                # start driver kalau belum ada
                if driver is None:
                    options = get_options(user_data_dir, profile_dir)
                    driver = webdriver.Chrome(options=options)
                    print(f"[{profile_name}] ({email}) Chrome started | user_data_dir={user_data_dir}")
                    if tg_enabled():
                        tg_send_message(f"✅ LOOP START: {profile_name}\nEmail: {email}\nuser_data_dir={user_data_dir}")

                round_num += 1

                # ✅ hapus loop log tiap 5 menit
                truncate_loop_log_if_needed(log_state)

                links = read_file_lines(shared_link_file)
                total_links = len(links)

                if local_num <= 0 or local_num > group_slots:
                    print(f"[{profile_name}] ROUND#{round_num} IDLE: local_num={local_num} di luar group_slots={group_slots} (sleep 10s)")
                    update_status(profile_name, state="IDLE_NO_LINKS", round_num=round_num, link_idx=0, link_total=total_links, current_link="")
                    time.sleep(10)
                    continue

                if total_links == 0:
                    print(f"[{profile_name}] ROUND#{round_num} IDLE: {os.path.basename(shared_link_file)} kosong / tidak ada (sleep 10s)")
                    update_status(profile_name, state="IDLE_NO_LINKS", round_num=round_num, link_idx=0, link_total=0, current_link="")
                    time.sleep(10)
                    continue

                if local_num > total_links:
                    print(f"[{profile_name}] ROUND#{round_num} IDLE: tidak ada link untuk local_num={local_num}, total_links={total_links} file={os.path.basename(shared_link_file)} (sleep 10s)")
                    update_status(profile_name, state="IDLE_NO_LINKS", round_num=round_num, link_idx=0, link_total=total_links, current_link="")
                    time.sleep(10)
                    continue

                # ✅ DISTRIBUSI STRIDE SESUAI group_slots:
                # slot i buka link i, i+group_slots, i+2*group_slots, ...
                start_index = local_num - 1
                indices = list(range(start_index, total_links, group_slots))

                print(f"[{profile_name}] ROUND#{round_num} file={os.path.basename(shared_link_file)} total_links={total_links} group_slots={group_slots} assigned={len(indices)}")
                update_status(profile_name, state="RUNNING", round_num=round_num, link_idx=0, link_total=total_links, current_link="", last_error="")

                for link_i in indices:
                    # ✅ hapus loop log tiap 5 menit (jaga kalau loop panjang)
                    truncate_loop_log_if_needed(log_state)

                    link = links[link_i]
                    global_idx = link_i + 1  # 1-based line number in jokoX.txt

                    print(f"[{profile_name}] ROUND#{round_num} OPEN #{global_idx}/{total_links} ({os.path.basename(shared_link_file)}): {link}")

                    # proses link biasa
                    ok, err = process_single_link(driver, profile_name, email, link, global_idx, total_links, round_num)
                    if not ok:
                        print(f"[{profile_name}] GAGAL: {link} -> {err}")

                print(f"[{profile_name}] ROUND#{round_num} selesai (assigned={len(indices)}). Ulang dari awal slot (sleep {SLEEP_AFTER_FULL_ROUND}s)...")
                update_status(profile_name, state="SLEEP_ROUND", round_num=round_num, link_idx=0, link_total=total_links, current_link="")
                time.sleep(SLEEP_AFTER_FULL_ROUND)

            except Exception as e:
                # ==============================
                # ✅ CRASH/ERROR RECOVERY (NEW)
                # ==============================
                err = f"{type(e).__name__}: {str(e)}"
                print(f"[{profile_name}] Worker crash (recovery): {err}")
                update_status(profile_name, state="CRASH_RECOVERING", last_error=err[:240])

                # screenshot kalau masih sempat
                if tg_enabled():
                    caption = f"⚠️ LOOP CRASH\nProfile: {profile_name}\nEmail: {email}\nError: {err[:300]}\nAction: close clone + clear cache + restart"
                    try:
                        if driver:
                            shot = save_fail_screenshot(driver, profile_name, prefix="CRASH")
                            if shot:
                                tg_send_photo(shot, caption)
                            else:
                                tg_send_message(caption)
                        else:
                            tg_send_message(caption)
                    except:
                        pass

                # close driver
                try:
                    if driver:
                        driver.quit()
                except:
                    pass
                driver = None

                # clear cache profile ini
                try:
                    cleanup_profile_cache(user_data_dir)
                except:
                    pass

                # tunggu sebentar lalu lanjut (akan start driver lagi)
                time.sleep(max(3, SLEEP_JIKA_ERROR))
                continue

    except Exception as e:
        print(f"[{profile_name}] Worker fatal crash: {type(e).__name__}: {e}")
        if tg_enabled():
            tg_send_message(f"⚠️ Worker fatal crash: {profile_name} ({email})\n{type(e).__name__}: {e}")
        update_status(profile_name, state="CRASH", last_error=f"{type(e).__name__}: {str(e)[:240]}")

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
        release_profile_lock(user_data_dir)
        update_status(profile_name, state="STOPPED")


# ======================
# MAIN
# ======================
if __name__ == "__main__":
    profiles = scan_joko_folders(PROFILES_ROOT)
    if not profiles:
        print(f"⚠️ Tidak ada folder 'jokoX' di {PROFILES_ROOT}. Jalankan login.py dulu.")
        time.sleep(10)
        raise SystemExit(0)

    # slot yang benar-benar dijalankan
    total_slots = min(len(profiles), MAX_PARALLEL) if MAX_PARALLEL > 0 else len(profiles)

    emails = read_emails(EMAIL_FILE)
    while len(emails) < len(profiles):
        emails.append("unknown@email")

    # ✅ hitung jumlah profile per group (untuk pembagian link sesuai jumlah clone yang ada)
    # yang dihitung hanya yang benar-benar akan dijalankan (<= total_slots)
    group_counts = {}
    started_profiles = profiles[:total_slots]

    for prof in started_profiles:
        name = (prof.get("name") or "").lower()
        n = 0
        if name.startswith("joko"):
            tail = name[4:]
            if tail.isdigit():
                n = int(tail)
        if n <= 0:
            continue
        group_idx = ((n - 1) // 10) + 1
        group_counts[group_idx] = group_counts.get(group_idx, 0) + 1

    procs = []
    started = 0

    for idx, prof in enumerate(profiles):
        if started >= total_slots:
            break

        profile_name = prof["name"]
        user_data_dir = prof["user_data_dir"]
        profile_dir = prof["profile_dir"]
        email = emails[idx] if idx < len(emails) else ""

        p = Process(target=worker, args=(profile_name, email, user_data_dir, profile_dir, total_slots, group_counts))
        p.start()
        procs.append(p)

        started += 1
        time.sleep(START_PROFILE_DELAY)

    for p in procs:
        p.join()
