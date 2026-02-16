# Python slim (bullseye)
FROM python:3.9-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /joko-app

# 1) System deps: xvfb + libs Chrome + tools yang dipakai agent.py
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl unzip gnupg2 jq xvfb xauth \
    procps psmisc \
    ca-certificates \
    fonts-liberation \
    libnss3 libxss1 libasound2 \
    libgbm1 libu2f-udev libvulkan1 \
    libgtk-3-0 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxrandr2 libxdamage1 libxcomposite1 libxfixes3 libxi6 \
    && rm -rf /var/lib/apt/lists/*

# 2) Install Google Chrome Stable (tanpa filter versi biar gak kosong)
RUN set -eux; \
    mkdir -p /etc/apt/keyrings; \
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google.gpg; \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends google-chrome-stable; \
    rm -rf /var/lib/apt/lists/*

# Disable Chrome Sync / Chrome Sign-in via Managed Policies (anti signout)
RUN set -eux; \
    mkdir -p /etc/opt/chrome/policies/managed; \
    printf '%s\n' \
    '{' \
    '  "SyncDisabled": true,' \
    '  "BrowserSignin": 0,' \
    '  "SigninAllowed": false,' \
    '  "PasswordManagerEnabled": false,' \
    '  "CredentialsEnableService": false' \
    '}' \
    > /etc/opt/chrome/policies/managed/policy.json

# 3) Install Chromedriver yang cocok dengan Chrome yang terpasang (Chrome for Testing public)
RUN set -eux; \
    CHROME_VER="$(google-chrome --version | awk '{print $3}')"; \
    echo ">> Detected Chrome version: ${CHROME_VER}"; \
    curl -fsSL -o /tmp/chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VER}/linux64/chromedriver-linux64.zip"; \
    unzip /tmp/chromedriver.zip -d /tmp/; \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver; \
    rm -rf /tmp/chromedriver.zip /tmp/chromedriver-linux64; \
    chmod +x /usr/local/bin/chromedriver; \
    # 🔥 FIX: buat_link.py minta /usr/bin/chromedriver
    ln -sf /usr/local/bin/chromedriver /usr/bin/chromedriver

# 4) Install cloudflared (dipakai entrypoint.sh)
RUN curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared

# 5) Python deps (yang dipakai agent/login/loop/buat_link)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      flask psutil requests \
      selenium==4.9.0 \
      selenium-stealth \
      Pillow pyvirtualdisplay mss pyautogui colorama

# 6) Copy semua file python kamu yang bener
COPY agent.py ./
COPY "login.py" ./login.py
COPY "loop.py" ./loop.py
COPY buat_link.py entrypoint.sh ./

# 7) Buat folder + file dummy yang sering dicari script
RUN mkdir -p chrome_profiles screenshots snapshots && \
    touch email.txt emailshare.txt mapping_profil.txt bot_log.txt \
          login_log.txt loop_log.txt buat_link_log.txt \
          loop_status.json tunnel.log && \
    chmod +x entrypoint.sh

# 8) Optional: kunci chrome biar ga update (biar tetap di major 120)
RUN apt-mark hold google-chrome-stable || true

# Biar selenium gak bingung cari binary/driver
ENV CHROME_BINARY=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

EXPOSE 8080
CMD ["./entrypoint.sh"]