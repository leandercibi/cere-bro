#!/usr/bin/env bash
# Deploy Cerebro to the OCI production server.
#
# Usage: ./scripts/deploy_prod.sh [--restart-only]
#   --restart-only   Skip git pull / pip install, just restart the service
#
# Prerequisites:
#   - SSH alias "oracle-lee" configured in ~/.ssh/config pointing at 92.5.33.117
#   - SSH key: ~/Downloads/key/re/oci/ssh-key-2026-05-28.key
#   - App lives at ~/cere-bro on the server
#   - .env file already present at ~/cere-bro/.env on the server
#   - systemd user service "cerebro" installed (see below)
#
# First-time service setup — run manually on the server:
#   mkdir -p ~/.config/systemd/user
#   cat > ~/.config/systemd/user/cerebro.service << 'EOF'
#   [Unit]
#   Description=Cerebro Telegram Bot
#   After=network.target
#
#   [Service]
#   Type=simple
#   WorkingDirectory=/home/ubuntu/cere-bro
#   ExecStart=/home/ubuntu/cere-bro/.venv/bin/cerebro
#   Restart=on-failure
#   RestartSec=10
#   StandardOutput=journal
#   StandardError=journal
#
#   [Install]
#   WantedBy=default.target
#   EOF
#   systemctl --user enable cerebro
#   loginctl enable-linger ubuntu

set -euo pipefail

REMOTE="oracle-lee"
APP_DIR="~/cere-bro"
RESTART_ONLY=false

for arg in "$@"; do
    [[ "$arg" == "--restart-only" ]] && RESTART_ONLY=true
done

if [[ "$RESTART_ONLY" == false ]]; then
    echo "==> Pulling latest code on $REMOTE..."
    ssh "$REMOTE" "cd $APP_DIR && git pull origin main"

    echo "==> Installing / updating dependencies..."
    ssh "$REMOTE" "cd $APP_DIR && .venv/bin/pip install -e '.' -q"
fi

echo "==> Restarting cerebro service..."
ssh "$REMOTE" "systemctl --user restart cerebro && systemctl --user status cerebro --no-pager -l"

echo "Done. Tail logs with: ssh $REMOTE 'journalctl --user -u cerebro -f'"
