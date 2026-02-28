#!/bin/bash
set -e

CODE_DIR="/joko-app"
BASE_DIR="${BASE_DIR:-/joko-app/data}"

# ==============================
# CONFIG TANPA .ENV (ISI DI SINI)
# ==============================
MONITOR_URL="http://213.163.203.144:9001"
MONITOR_API_KEY="Lolipop123#a"
REGISTER_EVERY=15                          

TG_TOKEN="8333206393:AAG8Z76SSbgAEAC1a3oPT8XhAF9t_rDOq3A"
TG_CHAT_ID="-1003532458425"
# ==============================

echo "========================================"
echo "🚀 JOKO BOT DOCKER STARTING..."
echo "CODE_DIR: $CODE_DIR"
echo "BASE_DIR: $BASE_DIR"
echo "MONITOR : $MONITOR_URL"
echo "========================================"

# --- CLEANUP ---
rm -f /tmp/.X99-lock || true
rm -f "$BASE_DIR/tunnel.log" || true

# --- ENSURE FOLDER & FILE ---
mkdir -p "$BASE_DIR/chrome_profiles"
mkdir -p "$BASE_DIR/screenshots"
mkdir -p "$BASE_DIR/snapshots"

touch "$BASE_DIR/email.txt"
touch "$BASE_DIR/emailshare.txt"
touch "$BASE_DIR/mapping_profil.txt"
touch "$BASE_DIR/bot_log.txt"
touch "$BASE_DIR/login_log.txt"
touch "$BASE_DIR/loop_log.txt"
touch "$BASE_DIR/buat_link_log.txt"
touch "$BASE_DIR/loop_status.json"
touch "$BASE_DIR/tunnel.log"

get_public_ip() {
  # IP publik VPS (kalau gagal fallback hostname)
  local ip=""
  ip="$(curl -fsS --max-time 6 https://ifconfig.me 2>/dev/null || true)"
  if [ -z "$ip" ]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi
  echo "${ip:-Unknown-IP}"
}

extract_tunnel_url() {
  grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' "$BASE_DIR/tunnel.log" | head -n 1 || true
}

post_register() {
  local name="$1"
  local url="$2"

  # kalau monitor belum diset → skip
  if [ -z "$MONITOR_URL" ] || [ -z "$MONITOR_API_KEY" ]; then
    return 0
  fi

  curl -fsS --max-time 8 \
    -X POST "$MONITOR_URL/register" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $MONITOR_API_KEY" \
    -d "{\"name\":\"$name\",\"url\":\"$url\"}" \
    >/dev/null 2>&1 || true
}

register_loop() {
  local ip name tunnel
  ip="$(get_public_ip)"
  name="VPS-${ip}"

  while true; do
    tunnel="$(extract_tunnel_url)"
    if [ -n "$tunnel" ]; then
      post_register "$name" "$tunnel"
    fi
    sleep "$REGISTER_EVERY"
  done
}

# --- START CLOUDFLARE TUNNEL ---
echo "🌐 Starting Cloudflare Tunnel..."
nohup cloudflared tunnel --url http://localhost:8080 > "$BASE_DIR/tunnel.log" 2>&1 &

echo "⏳ Waiting for tunnel URL..."
MAX_RETRY=40
COUNT=0
TUNNEL_URL=""

while [ -z "$TUNNEL_URL" ] && [ $COUNT -lt $MAX_RETRY ]; do
  sleep 2
  TUNNEL_URL="$(extract_tunnel_url)"
  COUNT=$((COUNT+1))
done

if [ -n "$TUNNEL_URL" ]; then
  echo "========================================"
  echo "✅ PUBLIC URL:"
  echo "$TUNNEL_URL"
  echo "========================================"

  # start background register loop (auto update agents.json)
  echo "🧾 Start register loop → $MONITOR_URL (every ${REGISTER_EVERY}s)"
  register_loop &
  REG_PID=$!

  # optional telegram
  if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT_ID" ]; then
    MSG="🚀 <b>JOKO BOT ONLINE</b>%0A%0A🌐 <code>$TUNNEL_URL</code>%0A✅ Status: RUNNING"
    curl -s -X POST "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
      -d chat_id="$TG_CHAT_ID" \
      -d text="$MSG" \
      -d parse_mode="HTML" >/dev/null 2>&1 || true
  fi
else
  echo "❌ Tunnel URL tidak ditemukan!"
  echo "Cek koneksi internet container."
fi

# --- START AGENT (PANEL) ---
echo "🖥️ Starting Agent Panel (Flask)..."
exec python3 -u "$CODE_DIR/agent.py"
