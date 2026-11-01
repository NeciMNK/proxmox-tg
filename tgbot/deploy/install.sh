#!/bin/bash
# Installs the Telegram bot for PegaProx as a systemd service.
# Run as root from the repository checkout:  bash tgbot/deploy/install.sh
# Works on the PegaProx host itself or on any other Debian/Ubuntu host that reaches it.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/opt/proxmox-tg-bot
ENV_FILE=/etc/proxmox-tg-bot.env
UNIT=/etc/systemd/system/proxmox-tg-bot.service

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root" >&2
    exit 1
fi

if ! command -v python3 >/dev/null || ! python3 -m venv --help >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv
fi

id proxmox-tg-bot >/dev/null 2>&1 || useradd --system --home-dir /var/lib/proxmox-tg-bot --shell /usr/sbin/nologin proxmox-tg-bot

mkdir -p "$DEST"
rm -rf "$DEST/tgbot"
cp -r "$SRC" "$DEST/tgbot"
find "$DEST/tgbot" -name '__pycache__' -prune -exec rm -rf {} +
[ -x "$DEST/venv/bin/python" ] || python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install -q --upgrade pip
"$DEST/venv/bin/pip" install -q -r "$DEST/tgbot/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
    install -m 0640 -o root -g proxmox-tg-bot "$SRC/deploy/proxmox-tg-bot.env.example" "$ENV_FILE"
    echo "Created $ENV_FILE: put the bot token (TG_BOT_TOKEN) there, then run:"
    echo "  systemctl restart proxmox-tg-bot"
fi

install -m 0644 "$SRC/deploy/proxmox-tg-bot.service" "$UNIT"
systemctl daemon-reload
systemctl enable proxmox-tg-bot >/dev/null
if grep -q '^TG_BOT_TOKEN=123456:ABC' "$ENV_FILE"; then
    echo "Bot installed but not started: TG_BOT_TOKEN in $ENV_FILE is still the example."
else
    systemctl restart proxmox-tg-bot
    echo "Bot started. Logs: journalctl -u proxmox-tg-bot -f"
fi
