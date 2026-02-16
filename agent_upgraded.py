import os
import re
import time
import json
import shutil
import socket
import psutil
import subprocess
from datetime import datetime
from threading import Thread
from flask import Flask, request, jsonify, Response, send_file
from shutil import which

# =========================
# CONFIG
# =========================
BASE_DIR = os.path.abspath(os.environ.get("BASE_DIR") or os.getcwd())
os.makedirs(BASE_DIR, exist_ok=True)

AGENT_HOST = "127.0.0.1"
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8080"))

PYTHON_BIN = os.environ.get("PYTHON_BIN") or (which("python3") or which("python") or os.path.join(BASE_DIR, "venv", "bin", "python"))

FILE_LOGIN = os.path.join(BASE_DIR, "login.py")
FILE_LOOP = os.path.join(BASE_DIR, "loop.py")

# ✅ NEW: buat_link.py
FILE_BUAT_LINK = os.path.join(BASE_DIR, "buat_link.py")
BUAT_LINK_LOG = os.path.join(BASE_DIR, "buat_link_log.txt")

# Main panel/event log
LOG_FILE = os.path.join(BASE_DIR, "bot_log.txt")

# per-script logs for monitor
LOGIN_LOG = os.path.join(BASE_DIR, "login_log.txt")
LOOP_LOG = os.path.join(BASE_DIR, "loop_log.txt")

TUNNEL_LOG = os.path.join(BASE_DIR, "tunnel.log")

EMAIL_FILE = os.path.join(BASE_DIR, "email.txt")
EMAILSHARE_FILE = os.path.join(BASE_DIR, "emailshare.txt")  # ✅ auto create
MAPPING_FILE = os.path.join(BASE_DIR, "mapping_profil.txt")

CHROME_PROFILES_DIR = os.path.join(BASE_DIR, "chrome_profiles")
os.makedirs(CHROME_PROFILES_DIR, exist_ok=True)

CLOUDFLARED_LOCAL = os.path.join(BASE_DIR, "bin", "cloudflared")

# 🔥 Loop status file (dibuat oleh loop.py)
LOOP_STATUS_FILE = os.path.join(BASE_DIR, "loop_status.json")

# Telegram (optional)
TG_TOKEN = os.environ.get("TG_TOKEN", "8333206393:AAG8Z76SSbgAEAC1a3oPT8XhAF9t_rDOq3A").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "-1003532458425").strip()

# Xvfb
SCREEN_LOGIN = os.environ.get("SCREEN_LOGIN") or "1280x720x24"
SCREEN_LOOP = os.environ.get("SCREEN_LOOP") or "1300x800x24"
SCREEN_BUAT_LINK = os.environ.get("SCREEN_BUAT_LINK") or "1280x720x24"

# JOKO files (compat)
JOKO_MIN = 1
JOKO_MAX = 5

# Tunnel
TUNNEL_URL_REGEX = r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com"

# Screenshots dirs (monitor)
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
PARENT_SCREENSHOT_DIR = os.path.join(os.path.dirname(BASE_DIR), "screenshots")

app = Flask(__name__)

# =========================
# NO-CACHE (fix mobile/tunnel cache)
# =========================
@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


# =========================
# UTILS
# =========================
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def append_line(path: str, line: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        if not line.endswith("\n"):
            line += "\n"
        f.write(line)

def safe_read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def safe_write_text(path: str, content: str):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)

def safe_read_json(path: str, default=None):
    if default is None:
        default = {}
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception:
        return default

def is_port_open(host: str, port: int, timeout=0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def run_bg(cmd: str):
    subprocess.Popen(cmd, shell=True)

def kill_by_keyword(keyword: str):
    os.system(f"pkill -f \"{keyword}\" > /dev/null 2>&1")

def kill_chrome_all():
    # close semua clone chrome profiles (sesuai request)
    kill_by_keyword("chromedriver")
    kill_by_keyword("google-chrome")
    kill_by_keyword("chrome")
    kill_by_keyword("chromium")
    kill_by_keyword("chromium-browser")

def kill_xvfb_runs():
    # pastikan xvfb-run yg nge-wrap script ikut berhenti
    kill_by_keyword("xvfb-run")
    kill_by_keyword("Xvfb")

def check_process_script(script_name: str) -> bool:
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or [])
            if script_name in cmd:
                return True
        except Exception:
            pass
    return False

def ensure_files():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    try:
        os.makedirs(PARENT_SCREENSHOT_DIR, exist_ok=True)
    except Exception:
        pass

    for f in [
        EMAIL_FILE,
        EMAILSHARE_FILE,
        MAPPING_FILE,
        LOG_FILE,
        LOGIN_LOG,
        LOOP_LOG,
        BUAT_LINK_LOG,
        TUNNEL_LOG,
    ]:
        if not os.path.exists(f):
            safe_write_text(f, "")

    # compat: tetap buat joko1..18 kalau belum ada
    for i in range(JOKO_MIN, JOKO_MAX + 1):
        p = os.path.join(BASE_DIR, f"joko{i}.txt")
        if not os.path.exists(p):
            safe_write_text(p, "")

    # loop status file (optional)
    if not os.path.exists(LOOP_STATUS_FILE):
        safe_write_text(LOOP_STATUS_FILE, "{}")

def tg_enabled():
    return bool(TG_TOKEN and TG_CHAT_ID)

def tg_send_message(text: str):
    if not tg_enabled():
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": text}, timeout=15)
    except Exception:
        pass

# =========================
# WORKSPACE NAME HELPERS (NEW)
# =========================
def extract_workspace_name(url: str) -> str:
    """Best-effort: ambil nama workspace dari URL yang sedang dibuka.
    Tidak ubah loop.py: kita derive dari current_link yang ditulis loop_status.json.
    """
    try:
        if not url:
            return ""
        u = (url or "").strip()
        u = u.split("#", 1)[0]
        from urllib.parse import urlparse, parse_qs, unquote
        p = urlparse(u)
        qs = parse_qs(p.query or "")
        for k in ("workspace", "ws", "project", "name", "id"):
            if k in qs and qs[k]:
                v = (qs[k][0] or "").strip()
                if v:
                    return unquote(v)[:80]
        parts = [x for x in (p.path or "").split("/") if x]
        if parts:
            cand = parts[-1]
            if cand.lower() in ("ide", "open", "workspace", "workspaces", "projects") and len(parts) >= 2:
                cand = parts[-2]
            return unquote(cand)[:80]
        return (p.hostname or "")[:80]
    except Exception:
        return ""

def drop_caches_linux():
    """Clear RAM cache (Linux) via /proc/sys/vm/drop_caches.
    Catatan: butuh permission (biasanya root)."""
    try:
        try:
            os.sync()
        except Exception:
            pass
        with open("/proc/sys/vm/drop_caches", "w", encoding="utf-8") as f:
            f.write("3\n")
        return True, "✅ drop_caches OK (echo 3 > /proc/sys/vm/drop_caches)"
    except PermissionError:
        return False, "❌ drop_caches butuh permission root"
    except Exception as e:
        return False, f"❌ drop_caches gagal: {type(e).__name__}: {e}"

def kill_all_processes_joko():
    """Kill semua proses yang relevan (login/loop/buat_link/chrome/xvfb)."""
    kill_by_keyword("login.py")
    kill_by_keyword("loop.py")
    kill_by_keyword("buat_link.py")
    kill_chrome_all()
    kill_xvfb_runs()



# =========================
# SAFE PATH
# =========================
def _safe_join(rel_path: str) -> str:
    rel_path = (rel_path or "").strip()
    if not rel_path:
        return ""
    if rel_path.startswith("joko/"):
        rel_path = rel_path[len("joko/"):]
    full = os.path.abspath(os.path.join(BASE_DIR, rel_path))
    base_abs = os.path.abspath(BASE_DIR)
    if not full.startswith(base_abs + os.sep) and full != base_abs:
        return ""
    return full

def resolve_filename(name: str) -> str:
    return _safe_join(name)


# =========================
# TUNNEL
# =========================
def tunnel_running() -> bool:
    for p in psutil.process_iter(["cmdline", "name"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or [])
            if "cloudflared" in cmd and "tunnel" in cmd and "--url" in cmd:
                return True
        except Exception:
            pass
    return False

def tunnel_url_from_log() -> str:
    text = safe_read_text(TUNNEL_LOG)
    matches = re.findall(TUNNEL_URL_REGEX, text)
    return matches[0] if matches else ""

def start_tunnel(local_url: str) -> str:
    if tunnel_running():
        return tunnel_url_from_log()

    try:
        if os.path.exists(TUNNEL_LOG):
            os.remove(TUNNEL_LOG)
    except Exception:
        pass

    cloudflared = "cloudflared" if which("cloudflared") else CLOUDFLARED_LOCAL
    cmd = f"nohup {cloudflared} tunnel --url {local_url} > {TUNNEL_LOG} 2>&1 &"
    run_bg(cmd)

    for _ in range(80):
        time.sleep(0.25)
        u = tunnel_url_from_log()
        if u:
            return u
    return ""

def stop_tunnel():
    kill_by_keyword("cloudflared tunnel --url")

def auto_start_tunnel_worker():
    """
    Auto start Cloudflare Quick Tunnel saat agent.py run.
    Print URL tunnel ke terminal + tulis ke log.
    Bisa dimatikan pakai env: DISABLE_TUNNEL=1
    """
    if os.environ.get("DISABLE_TUNNEL", "").strip() == "1":
        append_line(LOG_FILE, f"[{_now()}] AUTO_TUNNEL disabled via env")
        return

    if which("cloudflared") is None and not os.path.exists(CLOUDFLARED_LOCAL):
        append_line(LOG_FILE, f"[{_now()}] AUTO_TUNNEL skipped: cloudflared not found")
        print("[JOKO] AUTO_TUNNEL: cloudflared tidak ditemukan. Install dulu cloudflared.")
        return

    local = f"http://{AGENT_HOST}:{AGENT_PORT}"

    # tunggu panel ready (port listen)
    for _ in range(120):  # ~30 detik
        if is_port_open(AGENT_HOST, AGENT_PORT, timeout=0.2):
            break
        time.sleep(0.25)

    u = start_tunnel(local)

    if u:
        append_line(LOG_FILE, f"[{_now()}] AUTO_TUNNEL started: {u}")
        print("========================================")
        print("[JOKO] ✅ TUNNEL URL (PUBLIC):")
        print(u)
        print("========================================")
        try:
            tg_send_message(f"✅ JOKO Tunnel Active:\n{u}")
        except Exception:
            pass
    else:
        append_line(LOG_FILE, f"[{_now()}] AUTO_TUNNEL failed")
        print("[JOKO] AUTO_TUNNEL gagal dapat URL. Cek:", TUNNEL_LOG)
        
# =========================
# RESET
# =========================

# =========================
# LOGIN NOTIFIER (TAIL login_log.txt → Telegram)
# Tanpa ubah login.py: kita baca log dan kirim notif berdasarkan pola log.
# =========================
LOGIN_NOTIFY_STATE = os.path.join(BASE_DIR, "login_notify_state.json")

def _load_notify_state() -> dict:
    try:
        with open(LOGIN_NOTIFY_STATE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save_notify_state(state: dict):
    try:
        with open(LOGIN_NOTIFY_STATE, "w", encoding="utf-8") as f:
            json.dump(state or {}, f)
    except Exception:
        pass

def auto_login_notifier_worker():
    """
    Monitor LOGIN_LOG dan kirim notif Telegram saat:
    - mulai akun (#urutan) + profile
    - selesai ketik email
    - selesai ketik password
    """
    # kalau telegram tidak diset, tetap jalan tapi tidak ngirim
    state = _load_notify_state()
    offset = int(state.get("offset", 0) or 0)

    current_akun = None
    current_profile = None

    # regex mengikuti output login.py yang sekarang
    re_akun = re.compile(r"\[\s*▶\s*\]\s*AKUN\s*#\s*(\d+)", re.IGNORECASE)
    re_profile = re.compile(r"profile folder:\s*(.+)$", re.IGNORECASE)
    re_email_typed = re.compile(r"Email diketik:\s*(.+)$", re.IGNORECASE)
    re_pass_typed = re.compile(r"Password diketik", re.IGNORECASE)

    while True:
        try:
            if not os.path.exists(LOGIN_LOG):
                time.sleep(1.5)
                continue

            # kalau file kepotong/di-rotate, reset offset
            fsize = os.path.getsize(LOGIN_LOG)
            if offset > fsize:
                offset = 0

            with open(LOGIN_LOG, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(offset)
                chunk = f.read()
                offset = f.tell()

            if chunk:
                for raw in chunk.splitlines():
                    line = raw.strip()

                    m = re_akun.search(line)
                    if m:
                        current_akun = m.group(1)
                        current_profile = None  # akan diisi dari baris berikutnya
                        # notif "mulai akun"
                        tg_send_message(f"🚀 LOGIN START\n#email: {current_akun}\n#clone: (pending)\n{line}")
                        continue

                    m = re_profile.search(line)
                    if m:
                        # contoh: /joko-app/data/chrome_profiles/joko1 → ambil basename
                        pf = m.group(1).strip()
                        current_profile = os.path.basename(pf.rstrip("/")) or pf
                        if current_akun:
                            tg_send_message(f"📁 PROFILE DETECTED\n#email: {current_akun}\n#clone: {current_profile}")
                        continue

                    m = re_email_typed.search(line)
                    if m:
                        email = m.group(1).strip()
                        tg_send_message(
                            f"✉️ EMAIL DIKETIK\n#email: {current_akun or '-'}\n#clone: {current_profile or '-'}\n{email}"
                        )
                        continue

                    if re_pass_typed.search(line):
                        tg_send_message(
                            f"🔑 PASSWORD DIKETIK\n#email: {current_akun or '-'}\n#clone: {current_profile or '-'}"
                        )
                        continue

            state["offset"] = offset
            _save_notify_state(state)
            time.sleep(1.5)

        except Exception:
            # jangan bikin crash thread
            time.sleep(2.0)

def reset_mapping_file():
    safe_write_text(MAPPING_FILE, "")

def reset_chrome_profiles():
    p = os.path.abspath(CHROME_PROFILES_DIR)
    if p in ["/", "/root", os.path.abspath(BASE_DIR), os.path.abspath(os.path.dirname(BASE_DIR))]:
        raise RuntimeError("CHROME_PROFILES_DIR tidak aman untuk dihapus.")
    if os.path.exists(p):
        shutil.rmtree(p, ignore_errors=True)
    os.makedirs(p, exist_ok=True)


# =========================
# ROUTES - STATUS & LOGS
# =========================
@app.route("/status", methods=["GET"])
def status():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(BASE_DIR)

    # cpu_percent tanpa blocking lama
    try:
        cpu_pct = psutil.cpu_percent(interval=0.0)
    except Exception:
        cpu_pct = 0.0

    chrome_ok = False
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info.get("name") or "").lower()
            cmd = " ".join(p.info.get("cmdline") or []).lower()
            if "chrome" in name or "google-chrome" in cmd or "chromium" in cmd or "chrome" in cmd:
                chrome_ok = True
                break
        except Exception:
            pass

    novnc_ok = is_port_open("127.0.0.1", 6080) or False

    return jsonify({
        "login": check_process_script("login.py"),
        "loop": check_process_script("loop.py"),
        "buat_link": check_process_script("buat_link.py"),
        "chrome_opened": chrome_ok,
        "novnc_ready": novnc_ok,
        "tunnel_running": tunnel_running(),
        "tunnel_url": tunnel_url_from_log(),
        "ram_free_mb": int(mem.available // 1048576),
        "ram_used_mb": int((mem.total - mem.available) // 1048576),
        "ram_total_mb": int(mem.total // 1048576),
        "ram_used_percent": float(mem.percent),
        "cpu_percent": float(cpu_pct),
        "disk_used_percent": float(disk.percent),
        "disk_used_gb": round(disk.used / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "time": _now(),
        "base_dir": BASE_DIR,
        "screens_dir": SCREENSHOT_DIR,
        "profiles_dir": CHROME_PROFILES_DIR,
        "mapping_file": MAPPING_FILE
    })

def _tail(path: str, n: int = 250) -> str:
    if not os.path.exists(path):
        return ""
    try:
        return subprocess.check_output(["tail", "-n", str(n), path]).decode("utf-8", errors="ignore")
    except Exception as e:
        return f"Error reading logs: {e}"

@app.route("/logs", methods=["GET"])
def logs_all_compat():
    return jsonify({"logs": _tail(LOG_FILE, 250), "kind": "all"})

@app.route("/logs/<kind>", methods=["GET"])
def logs_kind(kind):
    kind = (kind or "all").lower().strip()
    if kind in ("all", "panel", "bot"):
        path = LOG_FILE
    elif kind == "login":
        path = LOGIN_LOG
    elif kind == "loop":
        path = LOOP_LOG
    elif kind in ("buat_link", "buatlink", "link"):
        path = BUAT_LINK_LOG
    else:
        return jsonify({"error": "kind invalid. use all|login|loop|buat_link"}), 400
    return jsonify({"logs": _tail(path, 350), "kind": kind})

# ✅ NEW: login monitor (ambil dari login_log.txt)
def _parse_login_monitor(text: str):
    """
    Cari progress login dari log:
    - akun terakhir yg sedang diproses
    - status terakhir (OTP / SUCCESS / ERROR) kalau ada
    """
    lines = (text or "").splitlines()
    last_acc = ""
    last_status = ""
    last_line = lines[-1] if lines else ""

    # cari akun terbaru: "[▶] AKUN #x | email"
    for ln in reversed(lines[-300:]):
        if "[▶] AKUN" in ln and "|" in ln:
            last_acc = ln.strip()
            break

    # cari marker yang sering muncul
    for ln in reversed(lines[-300:]):
        low = ln.lower()
        if "otp" in low or "verifikasi" in low:
            last_status = "OTP / VERIFIKASI"
            break
        if "login sukses" in low or "done" in low:
            last_status = "LOGIN SUKSES"
            break
        if "error" in low or "fail" in low:
            last_status = "ERROR"
            break

    return {
        "current": last_acc or "-",
        "status": last_status or "-",
        "last_line": last_line or "-",
    }

@app.route("/login/monitor", methods=["GET"])
def login_monitor():
    ensure_files()
    t = _tail(LOGIN_LOG, 250)
    info = _parse_login_monitor(t)
    return jsonify({
        "monitor": info,
        "tail": t,
        "time": _now()
    })

# ✅ NEW: halaman khusus logs (fix tombol view logs di mobile)
VIEW_LOGS_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <script src="https://cdn.tailwindcss.com"></script>
  <title>JOKO Logs</title>
</head>
<body class="bg-slate-950 text-slate-100">
  <div class="max-w-5xl mx-auto p-4">
    <div class="flex items-center justify-between gap-2">
      <div>
        <div class="text-xl font-bold">📄 Logs</div>
        <div class="text-slate-400 text-sm">Auto refresh • pilih jenis log</div>
      </div>
      <div class="flex gap-2">
        <a href="/" class="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700">Back</a>
      </div>
    </div>

    <div class="mt-3 flex flex-wrap gap-2">
      <button class="btn px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700" data-kind="all">Panel</button>
      <button class="btn px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700" data-kind="login">Login</button>
      <button class="btn px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700" data-kind="loop">Loop</button>
      <button class="btn px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700" data-kind="buat_link">Buat Link</button>
    </div>

    <div class="mt-3 text-xs text-slate-400">kind: <span id="kind">all</span></div>
    <pre id="box" class="mt-2 p-3 rounded-2xl bg-black/40 border border-slate-800 text-xs overflow-auto h-[70vh] whitespace-pre-wrap">loading...</pre>
  </div>

<script>
const box = document.getElementById("box");
const kindEl = document.getElementById("kind");
let current = "all";

async function load(){
  try{
    const r = await fetch("/logs/" + current, {cache:"no-store"});
    const j = await r.json();
    box.textContent = j.logs || "-";
    kindEl.textContent = current;
  }catch(e){
    box.textContent = "Error load logs: " + e;
  }
}

document.querySelectorAll(".btn").forEach(b=>{
  b.onclick = ()=>{ current = b.dataset.kind; load(); };
});

setInterval(load, 2500);
load();
</script>
</body>
</html>
"""

@app.route("/view_logs", methods=["GET"])
def view_logs():
    ensure_files()
    return Response(VIEW_LOGS_HTML, mimetype="text/html")


# =========================
# ROUTES - LOOP PROFILE MONITOR
# =========================
@app.route("/loop/profiles", methods=["GET"])
def loop_profiles():
    ensure_files()
    data = safe_read_json(LOOP_STATUS_FILE, default={})
    profiles = []
    for name, st in (data or {}).items():
        if not isinstance(st, dict):
            continue
        st2 = dict(st)
        st2["name"] = name
        # ✅ NEW: derive workspace name dari current_link
        st2["workspace_name"] = extract_workspace_name(st2.get("current_link",""))
        profiles.append(st2)

    def _key(x):
        n = x.get("name", "")
        if n.lower().startswith("joko"):
            suf = n[4:]
            if suf.isdigit():
                return (0, int(suf))
        return (1, n)

    profiles.sort(key=_key)
    return jsonify({"profiles": profiles, "time": _now()})


# =========================
# ROUTES - SCREENSHOT MONITOR + LIVE GALLERY
# =========================
def _list_screens():
    out = []
    for d in [SCREENSHOT_DIR, PARENT_SCREENSHOT_DIR]:
        if not os.path.isdir(d):
            continue
        try:
            for fn in os.listdir(d):
                if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    full = os.path.join(d, fn)
                    try:
                        mt = os.path.getmtime(full)
                    except Exception:
                        mt = 0
                    out.append((mt, fn, d))
        except Exception:
            pass
    out.sort(reverse=True)
    return out

@app.route("/screens/list", methods=["GET"])
def screens_list():
    ensure_files()
    files = _list_screens()[:200]
    return jsonify({
        "screens": [{"name": fn, "dir": d, "mtime": int(mt)} for mt, fn, d in files],
        "primary_dir": SCREENSHOT_DIR,
        "fallback_dir": PARENT_SCREENSHOT_DIR,
    })

@app.route("/screens/view", methods=["GET"])
def screens_view():
    ensure_files()
    name = (request.args.get("name") or "").strip()
    if not name:
        return "missing name", 400
    if "/" in name or "\\" in name or ".." in name:
        return "invalid name", 400
    for d in [SCREENSHOT_DIR, PARENT_SCREENSHOT_DIR]:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return send_file(p)
    return "not found", 404

@app.route("/screens/clear", methods=["POST"])
def screens_clear():
    """
    Clear ALL screenshots (2 folders) sesuai request.
    """
    ensure_files()
    deleted = []
    errors = []
    for d in [SCREENSHOT_DIR, PARENT_SCREENSHOT_DIR]:
        if not os.path.isdir(d):
            continue
        try:
            for fn in os.listdir(d):
                if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    p = os.path.join(d, fn)
                    try:
                        os.remove(p)
                        deleted.append(fn)
                    except Exception as e:
                        errors.append(f"{fn}: {e}")
        except Exception as e:
            errors.append(f"LISTDIR_FAIL({d}): {e}")

    append_line(LOG_FILE, f"[{_now()}] CLEAR screenshots: deleted={len(deleted)} err={len(errors)}")
    return jsonify({
        "msg": "✅ screenshots cleared",
        "deleted_count": len(deleted),
        "errors": errors[:20],
    })

def cleanup_root_png_files():
    """
    Compat: bersih-bersih png yang nyasar di BASE_DIR root (bukan folder screenshots)
    """
    ensure_files()
    deleted = []
    errors = []
    try:
        for fn in os.listdir(BASE_DIR):
            if not fn.lower().endswith(".png"):
                continue
            full_path = os.path.join(BASE_DIR, fn)
            if not os.path.isfile(full_path):
                continue
            try:
                os.remove(full_path)
                deleted.append(fn)
            except Exception as e:
                errors.append(f"{fn}: {e}")
    except Exception as e:
        errors.append(f"LISTDIR_FAIL: {e}")
    append_line(LOG_FILE, f"[{_now()}] CLEANUP root PNG: deleted={len(deleted)} err={len(errors)}")
    return deleted, errors

@app.route("/screens/cleanup_root_png", methods=["POST"])
def cleanup_root_png():
    deleted, errors = cleanup_root_png_files()
    return jsonify({
        "msg": "cleanup root png done",
        "deleted_count": len(deleted),
        "errors": errors[:20],
    })

# ✅ NEW: Open Live Gallery (thumbnail preview, auto refresh)
LIVE_GALLERY_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <script src="https://cdn.tailwindcss.com"></script>
  <title>JOKO Live</title>
</head>
<body class="bg-slate-950 text-slate-100">
  <div class="max-w-6xl mx-auto p-4">
    <div class="flex items-center justify-between gap-2">
      <div>
        <div class="text-xl font-bold">🖼️ Live Screenshots</div>
        <div class="text-slate-400 text-sm">Auto refresh • tap gambar untuk full</div>
      </div>
      <div class="flex gap-2">
        <button id="btnRefresh" class="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700">Refresh</button>
        <a href="/" class="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700">Back</a>
      </div>
    </div>

    <div id="grid" class="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2"></div>
    <div class="mt-3 text-xs text-slate-500">Last update: <span id="t">-</span></div>
  </div>

<script>
const grid = document.getElementById("grid");
const t = document.getElementById("t");

function card(name){
  const url = "/screens/view?name=" + encodeURIComponent(name);
  return `
    <a href="${url}" target="_blank" class="block rounded-2xl overflow-hidden border border-slate-800 bg-black/40 hover:border-slate-600">
      <div class="aspect-[9/16] bg-black/20 overflow-hidden">
        <img src="${url}" class="w-full h-full object-cover" loading="lazy" />
      </div>
      <div class="p-2 text-[11px] text-slate-300 break-all">${name}</div>
    </a>
  `;
}

async function load(){
  try{
    const r = await fetch("/screens/list", {cache:"no-store"});
    const j = await r.json();
    const items = (j.screens || []).slice(0, 40);
    grid.innerHTML = items.map(x => card(x.name)).join("");
    const now = new Date();
    t.textContent = now.toLocaleString();
  }catch(e){
    grid.innerHTML = `<div class="text-slate-400 text-sm">Error: ${e}</div>`;
  }
}

document.getElementById("btnRefresh").onclick = load;
setInterval(load, 4000);
load();
</script>
</body>
</html>
"""

@app.route("/live", methods=["GET"])
def live_gallery():
    ensure_files()
    return Response(LIVE_GALLERY_HTML, mimetype="text/html")


# =========================
# ROUTES - BOT CONTROLS
# =========================
@app.route("/start/login", methods=["POST"])
def start_login():
    if check_process_script("login.py"):
        return jsonify({"msg": "⚠️ Login sudah jalan (Skipped)"})

    append_line(LOGIN_LOG, f"[{_now()}] ===== START login =====")

    cmd = (
        "nohup xvfb-run -a "
        f"--server-args='-screen 0 {SCREEN_LOGIN}' "
        f"{PYTHON_BIN} -u {FILE_LOGIN} "
        f">> {LOGIN_LOG} 2>&1 &"
    )
    run_bg(cmd)
    append_line(LOG_FILE, f"[{_now()}] START login")
    return jsonify({"msg": "✅ Login Started"})

@app.route("/start/loop", methods=["POST"])
def start_loop():
    if check_process_script("loop.py"):
        return jsonify({"msg": "⚠️ Loop sudah jalan (Skipped)"})

    append_line(LOOP_LOG, f"[{_now()}] ===== START loop =====")

    cmd = (
        "nohup xvfb-run -a "
        f"--server-args='-screen 0 {SCREEN_LOOP}' "
        f"{PYTHON_BIN} -u {FILE_LOOP} "
        f">> {LOOP_LOG} 2>&1 &"
    )
    run_bg(cmd)
    append_line(LOG_FILE, f"[{_now()}] START loop")
    return jsonify({"msg": "✅ Loop Started"})

@app.route("/start/buat_link", methods=["POST"])
def start_buat_link():
    ensure_files()
    if not os.path.exists(FILE_BUAT_LINK):
        return jsonify({"error": f"buat_link.py tidak ditemukan di: {FILE_BUAT_LINK}"}), 400

    if check_process_script("buat_link.py"):
        return jsonify({"msg": "⚠️ buat_link.py sudah jalan (Skipped)"})

    append_line(BUAT_LINK_LOG, f"[{_now()}] ===== START buat_link =====")

    cmd = (
        "nohup xvfb-run -a "
        f"--server-args='-screen 0 {SCREEN_BUAT_LINK}' "
        f"{PYTHON_BIN} -u {FILE_BUAT_LINK} "
        f">> {BUAT_LINK_LOG} 2>&1 &"
    )
    run_bg(cmd)
    append_line(LOG_FILE, f"[{_now()}] START buat_link")
    return jsonify({"msg": "✅ buat_link Started"})

@app.route("/stop/login", methods=["POST"])
def stop_login():
    # stop login + close all chrome clones
    kill_by_keyword("login.py")
    kill_chrome_all()
    kill_xvfb_runs()
    append_line(LOG_FILE, f"[{_now()}] STOP login + CLOSE chrome")
    append_line(LOGIN_LOG, f"[{_now()}] ===== STOP login =====")
    return jsonify({"msg": "🛑 Login Stopped + Chrome Closed"})

@app.route("/stop/loop", methods=["POST"])
def stop_loop():
    # stop loop + close all chrome clones
    kill_by_keyword("loop.py")
    kill_chrome_all()
    kill_xvfb_runs()
    append_line(LOG_FILE, f"[{_now()}] STOP loop + CLOSE chrome")
    append_line(LOOP_LOG, f"[{_now()}] ===== STOP loop =====")
    return jsonify({"msg": "🛑 Loop Stopped + Chrome Closed"})

@app.route("/stop/buat_link", methods=["POST"])
def stop_buat_link():
    kill_by_keyword("buat_link.py")
    # buat_link kadang juga buka chrome → tutup semua juga biar bersih
    kill_chrome_all()
    kill_xvfb_runs()
    append_line(LOG_FILE, f"[{_now()}] STOP buat_link + CLOSE chrome")
    append_line(BUAT_LINK_LOG, f"[{_now()}] ===== STOP buat_link =====")
    return jsonify({"msg": "🛑 buat_link Stopped + Chrome Closed"})

@app.route("/stop/all", methods=["POST"])
def stop_all():
    kill_by_keyword("login.py")
    kill_by_keyword("loop.py")
    kill_by_keyword("buat_link.py")
    kill_chrome_all()
    kill_xvfb_runs()
    append_line(LOG_FILE, f"[{_now()}] STOP ALL + CLOSE chrome")
    append_line(LOGIN_LOG, f"[{_now()}] ===== STOP ALL (login) =====")
    append_line(LOOP_LOG, f"[{_now()}] ===== STOP ALL (loop) =====")
    append_line(BUAT_LINK_LOG, f"[{_now()}] ===== STOP ALL (buat_link) =====")
    return jsonify({"msg": "🛑 Stop ALL done + Chrome Closed"})

# =========================
# ROUTES - KILL ALL + CLEAR RAM (NEW)
# =========================
@app.route("/kill/all", methods=["POST"])
def kill_all():
    """Kill semua proses (login/loop/buat_link/chrome/xvfb)."""
    kill_all_processes_joko()
    append_line(LOG_FILE, f"[{_now()}] KILL ALL processes + CLOSE chrome")
    return jsonify({"msg": "🧨 KILL ALL done (login/loop/buat_link/chrome/xvfb)"} )

@app.route("/system/clear_ram", methods=["POST"])
def system_clear_ram():
    """Clear RAM cache (drop caches)."""
    ok, msg = drop_caches_linux()
    append_line(LOG_FILE, f"[{_now()}] CLEAR_RAM ok={ok} msg={msg}")
    return jsonify({"ok": ok, "msg": msg})



# =========================
# ROUTES - TUNNEL
# =========================
@app.route("/panel/start_tunnel_login", methods=["POST"])
def panel_start_tunnel_login():
    local = f"http://{AGENT_HOST}:{AGENT_PORT}"
    u = start_tunnel(local)
    if not check_process_script("login.py"):
        start_login()
    return jsonify({"msg": "✅ Tunnel + Login started", "tunnel_url": u})

@app.route("/panel/stop_tunnel", methods=["POST"])
def panel_stop_tunnel():
    stop_tunnel()
    append_line(LOG_FILE, f"[{_now()}] STOP tunnel")
    return jsonify({"msg": "🛑 Tunnel stopped"})


# =========================
# ROUTES - RESET (MAPPING & CHROME PROFILES)
# =========================
@app.route("/reset/mapping", methods=["POST"])
def reset_mapping():
    ensure_files()
    reset_mapping_file()
    append_line(LOG_FILE, f"[{_now()}] RESET mapping_profil.txt")
    return jsonify({"msg": "✅ mapping_profil.txt direset"})

@app.route("/reset/chrome_profiles", methods=["POST"])
def reset_profiles():
    ensure_files()
    try:
        # stop semua dulu biar aman
        kill_by_keyword("login.py")
        kill_by_keyword("loop.py")
        kill_by_keyword("buat_link.py")
        kill_chrome_all()
        kill_xvfb_runs()

        reset_chrome_profiles()
        append_line(LOG_FILE, f"[{_now()}] RESET chrome_profiles: {CHROME_PROFILES_DIR}")
        return jsonify({"msg": f"✅ chrome_profiles direset: {CHROME_PROFILES_DIR}"})
    except Exception as e:
        append_line(LOG_FILE, f"[{_now()}] RESET chrome_profiles FAIL: {e}")
        return jsonify({"error": str(e)}), 400


# =========================
# ROUTES - FILE EDITOR
# =========================
@app.route("/files/list", methods=["GET"])
def files_list():
    ensure_files()
    files = []
    for root, dirs, filenames in os.walk(BASE_DIR):
        for fn in filenames:
            rel = os.path.relpath(os.path.join(root, fn), BASE_DIR)
            files.append(rel)
    return jsonify({"files": sorted(files), "base_dir": BASE_DIR})

@app.route("/files/read", methods=["POST"])
def files_read():
    ensure_files()
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    path = resolve_filename(name)
    if not path:
        return jsonify({"error": "path tidak valid"}), 400
    if not os.path.exists(path):
        return jsonify({"error": "file tidak ditemukan"}), 404
    if os.path.isdir(path):
        return jsonify({"error": "path adalah folder, bukan file"}), 400
    return jsonify({"name": name, "path": path, "content": safe_read_text(path)})

@app.route("/files/write", methods=["POST"])
def files_write():
    ensure_files()
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    content = data.get("content", "")
    path = resolve_filename(name)
    if not path:
        return jsonify({"error": "path tidak valid"}), 400
    try:
        safe_write_text(path, content)
        append_line(LOG_FILE, f"[{_now()}] SAVE OK: {name} -> {path} ({len(content)} bytes)")
        return jsonify({"msg": "✅ saved", "name": name, "path": path, "bytes": len(content)})
    except Exception as e:
        append_line(LOG_FILE, f"[{_now()}] SAVE FAIL: {name} -> {path} :: {e}")
        return jsonify({"error": str(e), "name": name, "path": path}), 500

@app.route("/files/delete", methods=["POST"])
def files_delete():
    ensure_files()
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    recursive = bool(data.get("recursive", False))
    path = resolve_filename(name)
    if not path:
        return jsonify({"error": "path tidak valid"}), 400
    if not os.path.exists(path):
        return jsonify({"error": "tidak ditemukan"}), 404
    try:
        if os.path.isdir(path):
            if recursive:
                shutil.rmtree(path)
            else:
                os.rmdir(path)
        else:
            os.remove(path)
        append_line(LOG_FILE, f"[{_now()}] DELETE OK: {name} -> {path}")
        return jsonify({"msg": "✅ deleted", "name": name})
    except Exception as e:
        append_line(LOG_FILE, f"[{_now()}] DELETE FAIL: {name} -> {path} :: {e}")
        return jsonify({"error": str(e)}), 400

@app.route("/files/mkdir", methods=["POST"])
def files_mkdir():
    ensure_files()
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    path = resolve_filename(name)
    if not path:
        return jsonify({"error": "path tidak valid"}), 400
    try:
        os.makedirs(path, exist_ok=True)
        append_line(LOG_FILE, f"[{_now()}] MKDIR OK: {name} -> {path}")
        return jsonify({"msg": "✅ mkdir ok", "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/files/ensure_joko", methods=["POST"])
def files_ensure_joko():
    created = []
    for i in range(JOKO_MIN, JOKO_MAX + 1):
        p = os.path.join(BASE_DIR, f"joko{i}.txt")
        if not os.path.exists(p):
            safe_write_text(p, "")
            created.append(f"joko{i}.txt")
    return jsonify({"msg": "✅ ensured", "created": created})

@app.route("/files/add_link", methods=["POST"])
def files_add_link():
    ensure_files()
    data = request.get_json(silent=True) or {}
    n = int(data.get("joko", 0) or 0)
    link = (data.get("link") or "").strip()
    if not (JOKO_MIN <= n <= JOKO_MAX):
        return jsonify({"error": "joko harus 1..18"}), 400
    if not link:
        return jsonify({"error": "link kosong"}), 400
    p = os.path.join(BASE_DIR, f"joko{n}.txt")
    append_line(p, link)
    append_line(LOG_FILE, f"[{_now()}] ADD LINK -> joko{n}.txt: {link}")
    return jsonify({"msg": "✅ link added", "file": f"joko{n}.txt"})


# =========================
# AUTO CLEANUP THREADS
# =========================
def auto_cleanup_worker():
    while True:
        try:
            cleanup_root_png_files()
        except Exception as e:
            append_line(LOG_FILE, f"[{_now()}] AUTO CLEANUP ERROR: {e}")
        time.sleep(30 * 60)


# =========================
# PANEL UI (Modern + Login Monitor + Loop Monitor + Stats)
# =========================
PANEL_HTML = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <script src="https://cdn.tailwindcss.com"></script>
  <title>JOKO Control Center</title>

  <style>
    :root{
      --bg:#030712; --panel:rgba(17,24,39,.72); --panel2:rgba(15,23,42,.72);
      --border:rgba(148,163,184,.18); --text:#e5e7eb; --muted:#94a3b8; --accent:#38bdf8;
      --shadow: 0 18px 60px rgba(0,0,0,.35);
    }
    [data-theme="light"]{
      --bg:#f8fafc; --panel:rgba(255,255,255,.86); --panel2:rgba(255,255,255,.92);
      --border:rgba(15,23,42,.10); --text:#0f172a; --muted:#475569; --accent:#0284c7;
      --shadow: 0 18px 60px rgba(2,6,23,.12);
    }
    body{
      background: radial-gradient(1200px 700px at 10% -10%, rgba(56,189,248,.20), transparent 60%),
                  radial-gradient(900px 600px at 90% 0%, rgba(168,85,247,.14), transparent 55%),
                  radial-gradient(900px 700px at 40% 110%, rgba(34,197,94,.10), transparent 55%),
                  var(--bg);
      color:var(--text);
      transition:background .25s ease,color .25s ease;
    }
    .glass{ background:var(--panel); border:1px solid var(--border); box-shadow:var(--shadow); backdrop-filter: blur(14px); }
    .glass2{ background:var(--panel2); border:1px solid var(--border); box-shadow:var(--shadow); backdrop-filter: blur(14px); }
    .muted{ color:var(--muted); }
    .chip{ border:1px solid var(--border); background:rgba(2,6,23,.25); }
    [data-theme="light"] .chip{ background:rgba(2,6,23,.04); }
    .btn{ border:1px solid var(--border); background:rgba(2,6,23,.35); }
    [data-theme="light"] .btn{ background:rgba(2,6,23,.04); }
    .btn:hover{ filter: brightness(1.08); transform: translateY(-1px); }
    .btn:active{ transform: translateY(0px) scale(.99); }
    .focus-ring:focus{ outline: none; box-shadow: 0 0 0 3px rgba(56,189,248,.25); }
    .mono{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
    .scrollbar::-webkit-scrollbar{ height:10px; width:10px; }
    .scrollbar::-webkit-scrollbar-thumb{ background: rgba(148,163,184,.25); border-radius: 999px; }
    .scrollbar::-webkit-scrollbar-track{ background: transparent; }
  </style>
</head>

<body class="min-h-screen">
  <!-- Topbar -->
  <div class="sticky top-0 z-20">
    <div class="mx-auto max-w-7xl px-4 pt-4">
      <div class="glass rounded-3xl px-4 py-3 flex items-center justify-between gap-3">
        <div class="flex items-center gap-3 min-w-0">
          <div class="h-10 w-10 rounded-2xl flex items-center justify-center"
               style="background: linear-gradient(135deg, rgba(56,189,248,.22), rgba(168,85,247,.18)); border:1px solid var(--border);">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M12 2l8 4v6c0 5-3.5 9.7-8 10-4.5-.3-8-5-8-10V6l8-4z" stroke="currentColor" stroke-width="1.8" opacity=".9"/>
              <path d="M8 12h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" opacity=".9"/>
              <path d="M10 9h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" opacity=".75"/>
            </svg>
          </div>
          <div class="min-w-0">
            <div class="text-lg font-semibold tracking-tight truncate">JOKO Control Center</div>
            <div class="text-xs muted truncate">Professional operations dashboard • tunnel-ready • mobile-friendly</div>
          </div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <a id="tunnelUrl" href="#" target="_blank"
             class="hidden sm:inline-flex btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">
            Tunnel: <span class="ml-2 mono">-</span>
          </a>
          <button id="btnTheme" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Dark/Light</button>
          <a id="btnLogs" href="/view_logs" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">View Logs</a>
        </div>
      </div>
    </div>
  </div>

  <div class="mx-auto max-w-7xl px-4 pb-10 pt-6">
    <div class="grid lg:grid-cols-12 gap-4">
      <!-- Sidebar -->
      <div class="lg:col-span-3">
        <div class="glass rounded-3xl p-4">
          <div class="text-xs muted">System</div>
          <div class="mt-2 grid gap-2">
            <div class="chip rounded-2xl p-3">
              <div class="text-xs muted">Time</div>
              <div id="timeNow" class="mono text-sm mt-1">-</div>
            </div>
            <div class="chip rounded-2xl p-3">
              <div class="text-xs muted">Base Dir</div>
              <div id="baseDir" class="mono text-xs mt-1 break-all">-</div>
            </div>
            <div class="chip rounded-2xl p-3">
              <div class="text-xs muted">Chrome Profiles</div>
              <div id="profilesDir" class="mono text-xs mt-1 break-all">-</div>
            </div>
            <div class="chip rounded-2xl p-3">
              <div class="text-xs muted">Screenshots</div>
              <div id="screensDir" class="mono text-xs mt-1 break-all">-</div>
            </div>
          </div>

          <div class="mt-4">
            <div class="text-xs muted">Core Actions</div>
            <div class="mt-2 grid gap-2">
              <button id="btnStartLogin" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">▶ Start Login</button>
              <button id="btnStopLogin" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">■ Stop Login</button>

              <button id="btnStartLoop" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">▶ Start Loop</button>
              <button id="btnStopLoop" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">■ Stop Loop</button>

              <button id="btnStartBuatLink" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">▶ Start Buat Link</button>
              <button id="btnStopBuatLink" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">■ Stop Buat Link</button>

              <div class="grid grid-cols-2 gap-2 pt-1">
                <button id="btnStopAll" class="btn rounded-2xl px-3 py-2 text-sm font-semibold focus-ring">🛑 Stop All</button>
                <button id="btnKillAll" class="btn rounded-2xl px-3 py-2 text-sm font-semibold focus-ring">🧨 Kill All</button>
              </div>

              <div class="grid grid-cols-2 gap-2 pt-1">
                <button id="btnClearRam" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">🧠 Clear RAM</button>
                <button id="btnResetProfiles" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">♻ Reset Profiles</button>
              </div>
              <button id="btnResetMapping" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">🗺 Reset Mapping</button>

              <div class="grid grid-cols-2 gap-2 pt-1">
                <button id="btnStartTunnelLogin" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">🌐 Tunnel + Login</button>
                <button id="btnStopTunnel" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">⛔ Stop Tunnel</button>
              </div>
            </div>

            <div class="mt-4 text-[11px] muted">
              Tip: "Kill All" akan menutup semua chrome/xvfb/script. "Clear RAM" butuh permission root.
            </div>
          </div>
        </div>
      </div>

      <!-- Main -->
      <div class="lg:col-span-9 space-y-4">
        <!-- Status + KPIs -->
        <div class="glass rounded-3xl p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-sm muted">Operations</div>
              <div class="text-xl font-semibold tracking-tight">Live System Overview</div>
              <div class="text-xs muted mt-1">Smooth refresh • real-time CPU/RAM charts • production-ready layout</div>
            </div>
            <div class="flex gap-2">
              <button id="btnRefresh" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Refresh</button>
              <a id="btnOpenLive" href="/live" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Open Live</a>
            </div>
          </div>

          <div class="mt-4 grid md:grid-cols-4 gap-3">
            <div class="glass2 rounded-3xl p-4">
              <div class="text-xs muted">Login</div>
              <div id="stLogin" class="text-xl font-semibold mt-1">-</div>
            </div>
            <div class="glass2 rounded-3xl p-4">
              <div class="text-xs muted">Loop</div>
              <div id="stLoop" class="text-xl font-semibold mt-1">-</div>
            </div>
            <div class="glass2 rounded-3xl p-4">
              <div class="text-xs muted">Buat Link</div>
              <div id="stBuatLink" class="text-xl font-semibold mt-1">-</div>
            </div>
            <div class="glass2 rounded-3xl p-4">
              <div class="text-xs muted">noVNC</div>
              <div id="stNoVNC" class="text-xl font-semibold mt-1">-</div>
            </div>
          </div>

          <div class="mt-4 grid md:grid-cols-3 gap-3">
            <div class="glass2 rounded-3xl p-4">
              <div class="flex items-center justify-between">
                <div class="text-xs muted">CPU</div>
                <div class="text-xs muted">load <span id="loadVal" class="mono">-</span></div>
              </div>
              <div class="mt-2 flex items-end justify-between">
                <div class="text-3xl font-semibold"><span id="cpuVal">0</span><span class="text-base muted ml-1">%</span></div>
                <div class="text-xs muted">uptime <span id="uptimeVal" class="mono">-</span></div>
              </div>
              <canvas id="cpuChart" class="mt-3 w-full h-24 rounded-2xl"></canvas>
              <div class="hidden"><span id="cpuPct">-</span></div>
            </div>

            <div class="glass2 rounded-3xl p-4">
              <div class="flex items-center justify-between">
                <div class="text-xs muted">RAM</div>
                <div class="text-xs muted"><span class="mono"><span id="ramUsed">0</span> / <span id="ramTotal">0</span> GB</span></div>
              </div>
              <div class="mt-2 flex items-end justify-between">
                <div class="text-3xl font-semibold"><span id="ramVal">0</span><span class="text-base muted ml-1">%</span></div>
                <div class="text-xs muted">free <span id="ramFree" class="mono">-</span> MB</div>
              </div>
              <canvas id="ramChart" class="mt-3 w-full h-24 rounded-2xl"></canvas>
              <div class="hidden"><span id="ramPct">-</span></div>
            </div>

            <div class="glass2 rounded-3xl p-4">
              <div class="text-xs muted">Disk</div>
              <div class="mt-2 flex items-end justify-between">
                <div class="text-3xl font-semibold"><span id="diskPct">-</span><span class="text-base muted ml-1">%</span></div>
                <div class="text-xs muted"><span class="mono"><span id="diskUsedGb">-</span> / <span id="diskTotalGb">-</span> GB</span></div>
              </div>
              <div class="mt-3 text-xs muted">
                Monitoring file & profile growth is recommended for long-running sessions.
              </div>
            </div>
          </div>
        </div>

        <div class="glass rounded-3xl p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm font-semibold">Workspace / Profile Monitor</div>
              <div class="text-xs muted">Status per clone • workspace name auto-detect dari URL • live refresh</div>
            </div>
            <button id="btnProfilesRefresh" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Refresh</button>
          </div>
          <div id="profilesBox" class="mt-3 grid sm:grid-cols-2 xl:grid-cols-3 gap-3"></div>
        </div>

        <div class="glass rounded-3xl p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm font-semibold">Login Monitor</div>
              <div class="text-xs muted">Auto tail login_log.txt • useful for OTP & error tracking</div>
            </div>
            <button id="btnLoginMonRefresh" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Refresh</button>
          </div>

          <div class="mt-3 grid md:grid-cols-3 gap-3">
            <div class="glass2 rounded-3xl p-4">
              <div class="text-xs muted">Current</div>
              <div id="loginCur" class="mono text-xs mt-1 whitespace-pre-wrap break-words">-</div>
            </div>
            <div class="glass2 rounded-3xl p-4">
              <div class="text-xs muted">Status</div>
              <div id="loginSt" class="text-lg font-semibold mt-1">-</div>
              <div class="text-xs muted mt-2">Last line</div>
              <div id="loginLast" class="mono text-xs mt-1 whitespace-pre-wrap break-words">-</div>
            </div>
            <div class="glass2 rounded-3xl p-4">
              <div class="text-xs muted">Tail (preview)</div>
              <pre id="loginTail" class="mono text-[11px] mt-2 whitespace-pre-wrap max-h-44 overflow-auto scrollbar">-</pre>
            </div>
          </div>
        </div>

        <div class="glass rounded-3xl p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm font-semibold">Screenshots</div>
              <div class="text-xs muted">Quick list • clean all • open live gallery for mobile</div>
            </div>
            <div class="flex gap-2">
              <button id="btnScreensRefresh" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Refresh</button>
              <button id="btnScreensClear" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Clear</button>
              <button id="btnCleanupRootPng" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Cleanup Root PNG</button>
            </div>
          </div>
          <div id="screensBox" class="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2"></div>
        </div>

        <div class="glass rounded-3xl p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm font-semibold">File Manager</div>
              <div class="text-xs muted">Edit file txt (email, joko, mapping, logs) langsung dari panel</div>
            </div>
            <button id="btnFilesRefresh" class="btn rounded-2xl px-3 py-2 text-xs font-medium focus-ring">Refresh</button>
          </div>

          <div class="mt-3 grid lg:grid-cols-12 gap-3">
            <div class="lg:col-span-4 glass2 rounded-3xl p-3">
              <div class="text-xs muted mb-2">Files</div>
              <div id="filesList" class="max-h-64 overflow-auto scrollbar text-sm"></div>
            </div>

            <div class="lg:col-span-8 glass2 rounded-3xl p-3">
              <div class="flex flex-wrap items-center gap-2">
                <input id="fileName" class="focus-ring w-full md:w-auto flex-1 rounded-2xl px-3 py-2 text-sm mono"
                       style="background: rgba(2,6,23,.30); border:1px solid var(--border);"
                       placeholder="contoh: email.txt / joko1.txt / mapping_profil.txt" />
                <button id="btnFileRead" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">Read</button>
                <button id="btnFileSave" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">Save</button>
                <button id="btnFileDelete" class="btn rounded-2xl px-3 py-2 text-sm font-medium focus-ring">Delete</button>
              </div>
              <textarea id="fileContent" class="focus-ring mt-3 w-full h-64 rounded-2xl p-3 mono text-xs"
                        style="background: rgba(2,6,23,.30); border:1px solid var(--border);"
                        placeholder="Isi file..."></textarea>
            </div>
          </div>
        </div>

        <div class="text-center text-xs muted py-4">
          Built for long-running automation • keep profiles stable • designed like a company portfolio dashboard.
        </div>
      </div>
    </div>
  </div>

<script>
/* ========= Existing JS logic below (kept compatible) ========= */
</script>

<script>
const $ = (id)=>document.getElementById(id);

function setTheme(t){
  document.body.setAttribute("data-theme", t);
  localStorage.setItem("joko_theme", t);
}

async function api(path, method="GET", body=null){
  const opt = {method, headers:{"Content-Type":"application/json"}, cache:"no-store"};
  if(body!==null) opt.body = JSON.stringify(body);
  const r = await fetch(path, opt);
  return await r.json();
}

function pushHist(arr, v){
  arr.push(Number(v||0));
  while(arr.length>60) arr.shift();
}
const cpuHist=[], ramHist=[];

function drawLineChart(canvasId, data, label){
  const c = $(canvasId);
  if(!c) return;
  const ctx = c.getContext("2d");
  const w = c.width = c.clientWidth * (window.devicePixelRatio||1);
  const h = c.height = c.clientHeight * (window.devicePixelRatio||1);
  ctx.clearRect(0,0,w,h);

  ctx.globalAlpha = 1;
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel").trim() || "rgba(17,24,39,.72)";
  ctx.fillRect(0,0,w,h);

  ctx.strokeStyle = "rgba(148,163,184,.12)";
  ctx.lineWidth = 1;
  for(let i=1;i<=3;i++){
    const y = (h/4)*i;
    ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke();
  }

  const max = Math.max(...data, 100);
  const min = 0;
  const pad = 10 * (window.devicePixelRatio||1);
  const xStep = (w - pad*2) / Math.max(1, (data.length-1));
  ctx.beginPath();
  data.forEach((v, i)=>{
    const x = pad + i*xStep;
    const y = h - pad - ((v-min)/(max-min))*(h - pad*2);
    if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  });
  ctx.strokeStyle = "rgba(56,189,248,.85)";
  ctx.lineWidth = 2.2*(window.devicePixelRatio||1);
  ctx.stroke();

  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted").trim() || "#94a3b8";
  ctx.font = `${14*(window.devicePixelRatio||1)}px ui-sans-serif, system-ui`;
  ctx.fillText(label, 12*(window.devicePixelRatio||1), 20*(window.devicePixelRatio||1));
}

function fmtGB(bytes){
  return (bytes / (1024*1024*1024)).toFixed(1);
}

async function refreshMetrics(){
  try{
    const j = await api("/api/metrics");
    $("cpuVal").textContent = (j.cpu_percent ?? 0).toFixed(0);
    $("ramVal").textContent = (j.mem_percent ?? 0).toFixed(0);
    $("ramUsed").textContent = fmtGB(j.mem_used ?? 0);
    $("ramTotal").textContent = fmtGB(j.mem_total ?? 0);
    $("loadVal").textContent = (j.load1 ?? "-");
    $("uptimeVal").textContent = (j.uptime ?? "-");

    pushHist(cpuHist, j.cpu_percent ?? 0);
    pushHist(ramHist, j.mem_percent ?? 0);
    drawLineChart("cpuChart", cpuHist, "CPU % (last 60s)");
    drawLineChart("ramChart", ramHist, "RAM % (last 60s)");
  }catch(e){}
}

function setStatus(id, v){
  $(id).textContent = v ? "RUNNING" : "STOPPED";
  $(id).className = "text-xl font-semibold " + (v ? "text-emerald-400" : "text-rose-400");
}

async function refreshStatus(){
  const s = await api("/status");
  setStatus("stLogin", s.login);
  setStatus("stLoop", s.loop);
  setStatus("stBuatLink", s.buat_link);
  setStatus("stNoVNC", s.novnc_ready);

  $("tunnelUrl").textContent = s.tunnel_url || "-";
  $("tunnelUrl").href = s.tunnel_url || "#";

  $("baseDir").textContent = s.base_dir || "-";
  $("screensDir").textContent = s.screens_dir || "-";
  $("timeNow").textContent = s.time || "-";

  $("cpuPct").textContent = (s.cpu_percent ?? "-");
  $("ramFree").textContent = (s.ram_free_mb ?? "-");
  $("ramUsed").textContent = (s.ram_used_mb ?? "-");
  $("ramTotal").textContent = (s.ram_total_mb ?? "-");
  $("ramPct").textContent = (s.ram_used_percent ?? "-");

  $("diskPct").textContent = (s.disk_used_percent ?? "-");
  $("diskUsedGb").textContent = (s.disk_used_gb ?? "-");
  $("diskTotalGb").textContent = (s.disk_total_gb ?? "-");

  $("profilesDir").textContent = (s.profiles_dir ?? "-");
}

function profileCard(p){
  const last = p.last_update || "-";
  const round = (p.round_num ?? "-");
  const idx = (p.link_idx ?? "-");
  const total = (p.link_total ?? "-");
  const link = (p.current_link || "-");
  const ws = (p.workspace_name || "");
  const state = (p.state || "-");
  const err = (p.last_error || "");

  const color = state.includes("ERROR") ? "border-rose-700/60" : (state.includes("RUN") ? "border-emerald-700/50" : "border-slate-700/40");

  return `
    <div class="glass2 rounded-3xl p-4 border ${color}">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <div class="text-sm font-semibold truncate">${p.name || "-"}</div>
          <div class="text-xs muted mt-0.5 truncate">${ws ? ("Workspace: " + ws) : "Workspace: -"}</div>
        </div>
        <div class="text-[11px] muted mono">${last}</div>
      </div>

      <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div class="chip rounded-2xl p-2">
          <div class="muted">State</div>
          <div class="font-semibold mt-0.5">${state}</div>
        </div>
        <div class="chip rounded-2xl p-2">
          <div class="muted">Round</div>
          <div class="font-semibold mt-0.5">${round}</div>
        </div>
        <div class="chip rounded-2xl p-2 col-span-2">
          <div class="muted">Link Progress</div>
          <div class="font-semibold mt-0.5">${idx} / ${total}</div>
          <div class="mono text-[11px] muted mt-1 break-all">${link}</div>
        </div>
      </div>

      ${err ? `<div class="mt-3 text-[11px] text-rose-300 mono whitespace-pre-wrap break-words">${err}</div>` : ""}
    </div>
  `;
}

async function refreshProfiles(){
  try{
    const j = await api("/loop/profiles");
    const arr = j.profiles || [];
    $("profilesBox").innerHTML = arr.map(profileCard).join("") || `<div class="muted text-sm">No profiles data.</div>`;
  }catch(e){
    $("profilesBox").innerHTML = `<div class="text-rose-300 text-sm">Error load profiles: ${e}</div>`;
  }
}

function screenCard(s){
  const url = "/screens/view?name=" + encodeURIComponent(s.name);
  return `
    <a href="${url}" target="_blank" class="block rounded-2xl overflow-hidden border" style="border-color:var(--border); background: rgba(2,6,23,.25);">
      <div class="aspect-[9/16] bg-black/20 overflow-hidden">
        <img src="${url}" class="w-full h-full object-cover" loading="lazy" />
      </div>
      <div class="p-2 text-[11px] muted mono break-all">${s.name}</div>
    </a>
  `;
}

async function refreshScreens(){
  try{
    const j = await api("/screens/list");
    const items = (j.screens || []).slice(0, 40);
    $("screensBox").innerHTML = items.map(screenCard).join("") || `<div class="muted text-sm">No screenshots.</div>`;
  }catch(e){
    $("screensBox").innerHTML = `<div class="text-rose-300 text-sm">Error load screens: ${e}</div>`;
  }
}

async function refreshLoginMonitor(){
  try{
    const j = await api("/login/monitor");
    const m = j.monitor || {};
    $("loginCur").textContent = m.current || "-";
    $("loginSt").textContent = m.status || "-";
    $("loginLast").textContent = m.last_line || "-";
    $("loginTail").textContent = j.tail || "-";
  }catch(e){}
}

let lastFiles = [];
function filesRender(list){
  const box = $("filesList");
  box.innerHTML = (list||[]).map(fn => `
    <button class="w-full text-left px-3 py-2 rounded-2xl hover:opacity-90 btn focus-ring mono text-xs"
            onclick="selectFile('${fn.replace(/'/g,"\\'")}')">${fn}</button>
  `).join("");
}

window.selectFile = (fn)=>{ $("fileName").value = fn; };

async function refreshFiles(){
  try{
    const j = await api("/files/list");
    lastFiles = j.files || [];
    filesRender(lastFiles);
  }catch(e){}
}

async function fileRead(){
  const name = ($("fileName").value || "").trim();
  if(!name) return alert("isi fileName dulu");
  const j = await api("/files/read","POST",{name});
  if(j.error) return alert(j.error);
  $("fileContent").value = j.content || "";
}

async function fileSave(){
  const name = ($("fileName").value || "").trim();
  if(!name) return alert("isi fileName dulu");
  const content = $("fileContent").value || "";
  const j = await api("/files/write","POST",{name, content});
  if(j.error) return alert(j.error);
  alert(j.msg || "saved");
  await refreshFiles();
}

async function fileDelete(){
  const name = ($("fileName").value || "").trim();
  if(!name) return alert("isi fileName dulu");
  if(!confirm("Delete file/folder? " + name)) return;
  const j = await api("/files/delete","POST",{name, recursive:true});
  if(j.error) return alert(j.error);
  alert(j.msg || "deleted");
  $("fileContent").value = "";
  await refreshFiles();
}

$("btnRefresh").onclick = async ()=>{ await refreshStatus(); await refreshMetrics(); await refreshProfiles(); await refreshScreens(); await refreshFiles(); };

$("btnStartLogin").onclick = async ()=>{ await api("/start/login","POST"); await refreshStatus(); };
$("btnStopLogin").onclick = async ()=>{ await api("/stop/login","POST"); await refreshStatus(); };

$("btnStartLoop").onclick = async ()=>{ await api("/start/loop","POST"); await refreshStatus(); };
$("btnStopLoop").onclick = async ()=>{ await api("/stop/loop","POST"); await refreshStatus(); };

$("btnStartBuatLink").onclick = async ()=>{ await api("/start/buat_link","POST"); await refreshStatus(); };
$("btnStopBuatLink").onclick = async ()=>{ await api("/stop/buat_link","POST"); await refreshStatus(); };

$("btnStopAll").onclick = async ()=>{ await api("/stop/all","POST"); await refreshStatus(); };
$("btnKillAll").onclick = async ()=>{ if(!confirm("KILL ALL processes + close chrome?")) return; await api("/kill/all","POST"); await refreshStatus(); };

$("btnClearRam").onclick = async ()=>{ const r=await api("/system/clear_ram","POST"); alert(r.msg || "done"); await refreshStatus(); };

$("btnResetMapping").onclick = async ()=>{
  if(!confirm("Reset mapping_profil.txt ?")) return;
  const r = await api("/reset/mapping","POST");
  alert(r.msg || r.error || "done");
};

$("btnResetProfiles").onclick = async ()=>{
  if(!confirm("Reset chrome_profiles? Ini akan STOP semua & close Chrome.")) return;
  const r = await api("/reset/chrome_profiles","POST");
  alert(r.msg || r.error || "done");
  await refreshStatus();
};

$("btnStartTunnelLogin").onclick = async ()=>{
  const r = await api("/panel/start_tunnel_login","POST");
  await refreshStatus();
  if(r.tunnel_url) window.open(r.tunnel_url, "_blank");
};
$("btnStopTunnel").onclick = async ()=>{ await api("/panel/stop_tunnel","POST"); await refreshStatus(); };

$("btnScreensRefresh").onclick = refreshScreens;
$("btnScreensClear").onclick = async ()=>{
  if(!confirm("Clear ALL screenshots?")) return;
  const r = await api("/screens/clear","POST",{});
  alert(`cleared: ${r.deleted_count || 0}`);
  await refreshScreens();
};
$("btnCleanupRootPng").onclick = async ()=>{ await api("/screens/cleanup_root_png","POST"); alert("cleanup done"); };

$("btnFilesRefresh").onclick = refreshFiles;
$("btnFileRead").onclick = fileRead;
$("btnFileSave").onclick = fileSave;
$("btnFileDelete").onclick = fileDelete;

$("btnLoginMonRefresh").onclick = refreshLoginMonitor;
$("btnProfilesRefresh").onclick = refreshProfiles;

setInterval(refreshLoginMonitor, 3500);
setInterval(refreshScreens, 12000);

setTheme(localStorage.getItem("joko_theme") || "dark");
$("btnTheme").onclick = ()=> setTheme((document.body.getAttribute("data-theme")==="light") ? "dark" : "light");

refreshStatus();
refreshLoginMonitor();
refreshProfiles();
refreshScreens();
refreshFiles();
refreshMetrics();

setInterval(refreshProfiles, 1500);
setInterval(refreshMetrics, 1000);
</script>
</body>
</html>
"""


@app.route("/api/metrics", methods=["GET"])
def api_metrics():
    """System metrics untuk dashboard charts."""

    try:
        cpu = float(psutil.cpu_percent(interval=0.15))
    except Exception:
        cpu = 0.0

    try:
        vm = psutil.virtual_memory()
        mem_percent = float(vm.percent)
        mem_used = int(getattr(vm, "used", 0))
        mem_total = int(getattr(vm, "total", 0))
    except Exception:
        mem_percent, mem_used, mem_total = 0.0, 0, 0

    load1 = "-"
    try:
        if hasattr(os, "getloadavg"):
            load1 = f"{os.getloadavg()[0]:.2f}"
    except Exception:
        pass

    uptime = "-"
    try:
        boot = psutil.boot_time()
        sec = max(0, int(time.time() - boot))
        h = sec // 3600
        mi = (sec % 3600) // 60
        s = sec % 60
        uptime = f"{h:02d}:{mi:02d}:{s:02d}"
    except Exception:
        pass

    return jsonify({
        "cpu_percent": cpu,
        "mem_percent": mem_percent,
        "mem_used": mem_used,
        "mem_total": mem_total,
        "load1": load1,
        "uptime": uptime,
        "ts": _now(),
    })

@app.route("/", methods=["GET"])
def panel_home():
    ensure_files()
    return Response(PANEL_HTML, mimetype="text/html")


# =========================
# START THREADS
# =========================
def start_background_threads():
    t = Thread(target=auto_cleanup_worker, daemon=True)
    t.start()
    
    t2 = Thread(target=auto_start_tunnel_worker, daemon=True)
    t2.start()

    # notif Telegram dari login_log.txt (tanpa ubah login.py)
    t3 = Thread(target=auto_login_notifier_worker, daemon=True)
    t3.start()


if __name__ == "__main__":
    ensure_files()
    start_background_threads()
    print(f"[JOKO] Panel running at http://{AGENT_HOST}:{AGENT_PORT}")
    print(f"[JOKO] BASE_DIR = {BASE_DIR}")
    print(f"[JOKO] CHROME_PROFILES_DIR = {CHROME_PROFILES_DIR}")
    app.run(host=AGENT_HOST, port=AGENT_PORT, debug=False)