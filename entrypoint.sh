#!/bin/bash
set -e

CODE_DIR="/joko-app"
BASE_DIR="${BASE_DIR:-/joko-app/data}"

echo "========================================"
echo "🚀 JOKO BOT DOCKER STARTING..."
echo "CODE_DIR: $CODE_DIR"
echo "BASE_DIR: $BASE_DIR"
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

# --- START CLOUDFLARE TUNNEL ---
echo "🌐 Starting Cloudflare Tunnel..."
nohup cloudflared tunnel --url http://localhost:8080 > "$BASE_DIR/tunnel.log" 2>&1 &

echo "⏳ Waiting for tunnel URL..."
MAX_RETRY=40
COUNT=0
TUNNEL_URL=""

while [ -z "$TUNNEL_URL" ] && [ $COUNT -lt $MAX_RETRY ]; do
  sleep 2
  TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' "$BASE_DIR/tunnel.log" | head -n 1 || true)
  COUNT=$((COUNT+1))
done

if [ ! -z "$TUNNEL_URL" ]; then
    echo "========================================"
    echo "✅ PUBLIC URL:"
    echo "$TUNNEL_URL"
    echo "========================================"

    if [ ! -z "$TG_TOKEN" ]; then
        MSG="🚀 <b>JOKO BOT ONLINE</b>%0A%0A🌐 <code>$TUNNEL_URL</code>%0A✅ Status: RUNNING"
        curl -s -X POST "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
            -d chat_id="$TG_CHAT_ID" \
            -d text="$MSG" \
            -d parse_mode="HTML" > /dev/null
    fi
else
    echo "❌ Tunnel URL tidak ditemukan!"
    echo "Cek koneksi internet container."
fi

# --- START AGENT (PANEL) ---
echo "🖥️ Starting Agent Panel (Flask)..."
exec python3 -u "$CODE_DIR/agent.py"