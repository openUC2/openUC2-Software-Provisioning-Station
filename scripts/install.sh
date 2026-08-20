#!/usr/bin/env bash
# Install the openUC2 Provisioning Station on Raspberry Pi OS (Lite works;
# kiosk setup adds a minimal X session with Chromium).
#
# Usage:
#   sudo bash scripts/install.sh            # backend + service
#   sudo bash scripts/install.sh --kiosk    # ... plus touchscreen kiosk mode
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo bash scripts/install.sh [--kiosk]" >&2
    exit 1
fi

KIOSK=0
[[ "${1:-}" == "--kiosk" ]] && KIOSK=1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR=/opt/uc2-provision
KIOSK_USER=${SUDO_USER:-pi}

echo "==> Installing system dependencies"
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    xz-utils util-linux udisks2 git curl

echo "==> Copying application to ${INSTALL_DIR}"
mkdir -p "$INSTALL_DIR"
# .git is deliberately preserved: the station updates itself in place with
# `git fetch && git reset --hard origin/<branch>` from the Settings page.
rsync -a --delete \
    --exclude backend/.venv --exclude frontend/node_modules \
    "$REPO_DIR"/ "$INSTALL_DIR"/

if [[ -d "$INSTALL_DIR/.git" ]]; then
    # Actions commits the built frontend to the branch, so make sure the
    # station tracks a real upstream branch it can fast-forward onto.
    branch="$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
    git -C "$INSTALL_DIR" fetch --quiet origin "$branch" 2>/dev/null \
        && git -C "$INSTALL_DIR" branch --set-upstream-to="origin/$branch" "$branch" >/dev/null 2>&1 \
        || echo "    (no network / no origin — in-place updates will need one)"
else
    echo "    WARNING: installed without a .git directory — the 'Update station'"
    echo "    button will be unavailable. Install from a git clone to enable it."
fi

echo "==> Setting up Python backend"
python3 -m venv "$INSTALL_DIR/backend/.venv"
"$INSTALL_DIR/backend/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/backend/.venv/bin/pip" install -q -e "$INSTALL_DIR/backend"

if [[ ! -d "$INSTALL_DIR/frontend/dist" ]]; then
    echo "==> No frontend/dist found — building frontend (needs nodejs+npm)"
    if ! command -v npm >/dev/null; then
        apt-get install -y nodejs npm
    fi
    (cd "$INSTALL_DIR/frontend" && npm install --no-audit --no-fund && npm run build)
fi

echo "==> Installing systemd service"
install -m 644 "$INSTALL_DIR/scripts/uc2-provision.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now uc2-provision.service

if [[ $KIOSK -eq 1 ]]; then
    echo "==> Setting up Chromium kiosk for user ${KIOSK_USER}"
    apt-get install -y --no-install-recommends \
        xserver-xorg x11-xserver-utils xinit openbox unclutter
    # Debian/Raspberry Pi OS renamed the package from chromium-browser to
    # chromium at some point; install whichever is available.
    apt-get install -y --no-install-recommends chromium-browser \
        || apt-get install -y --no-install-recommends chromium

    # The touchscreen panel is mounted rotated 180 degrees in the enclosure;
    # flip both the video output and the touch coordinates to match.
    install -m 644 /dev/stdin /etc/X11/xorg.conf.d/95-touchscreen-rotate.conf <<'EOF'
Section "InputClass"
    Identifier "touchscreen-rotate"
    MatchIsTouchscreen "on"
    Driver "libinput"
    Option "TransformationMatrix" "-1 0 1 0 -1 1 0 0 1"
EndSection
EOF

    KIOSK_HOME=$(getent passwd "$KIOSK_USER" | cut -d: -f6)
    mkdir -p "$KIOSK_HOME/.config/openbox"
    cat > "$KIOSK_HOME/.config/openbox/autostart" <<'EOF'
# Disable screen blanking on the station display
xset s off
xset s noblank
xset -dpms
# Physical panel is mounted rotated 180 degrees in the enclosure.
xrandr --output DSI-1 --rotate inverted
unclutter -idle 3 &
CHROMIUM=$(command -v chromium-browser || command -v chromium)
"$CHROMIUM" \
    --kiosk http://localhost:8000 \
    --noerrdialogs \
    --disable-infobars \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --check-for-update-interval=31536000
EOF
    chown -R "$KIOSK_USER":"$KIOSK_USER" "$KIOSK_HOME/.config"

    PROFILE="$KIOSK_HOME/.bash_profile"
    if ! grep -q "startx" "$PROFILE" 2>/dev/null; then
        cat >> "$PROFILE" <<'EOF'
# Auto-start the kiosk on the physical console
if [[ -z $DISPLAY && $(tty) == /dev/tty1 ]]; then
    exec startx -- -nocursor
fi
EOF
        chown "$KIOSK_USER":"$KIOSK_USER" "$PROFILE"
    fi

    echo "==> Enabling console autologin for ${KIOSK_USER}"
    if command -v raspi-config >/dev/null; then
        raspi-config nonint do_boot_behaviour B2 || true
    else
        mkdir -p /etc/systemd/system/getty@tty1.service.d
        cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${KIOSK_USER} --noclear %I \$TERM
EOF
        systemctl daemon-reload
    fi
fi

echo
echo "Done. Backend: http://localhost:8000  (service: uc2-provision)"
echo "Next steps:"
echo "  1. Open Settings in the UI and paste a GitHub token (repo/actions:read)"
echo "     — required to download os-rpi images (they are CI artifacts)."
echo "  2. Library → 'Auto-download latest' to pre-seed the cache."
[[ $KIOSK -eq 1 ]] && echo "  3. Reboot to start the kiosk: sudo reboot"
