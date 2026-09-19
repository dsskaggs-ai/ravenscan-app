#!/usr/bin/env bash
# ==============================================================================
# RavenScan - Scanner Permissions & System Setup for Omarchy / Arch Linux
# ==============================================================================

set -euo pipefail

echo "=== Raven Scanner (Avision AD215W) Setup ==="
echo ""

UDEV_RULE_FILE="/etc/udev/rules.d/99-raven-scanner.rules"
AVISION_CONF="/etc/sane.d/avision.conf"
SCANNER_GROUP="scanner"

echo "0. Ensuring '$SCANNER_GROUP' group exists and user is a member..."
if ! getent group "$SCANNER_GROUP" >/dev/null; then
    sudo groupadd "$SCANNER_GROUP"
fi
if ! id -nG "$USER" | grep -qw "$SCANNER_GROUP"; then
    sudo usermod -aG "$SCANNER_GROUP" "$USER"
    echo "   NOTE: log out and back in (or 'newgrp $SCANNER_GROUP') for group membership to take effect."
fi

echo "1. Creating udev rules for Raven Scanner (VID 0638, all supported PIDs)..."
# MODE 0660 + GROUP + uaccess: access limited to the scanner group and the
# active seat — NOT world-writable.
sudo tee "$UDEV_RULE_FILE" > /dev/null << 'EOF'
# Raven Compact Scanner (Avision AD215W/AD215)
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="3200", MODE="0660", GROUP="scanner", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="2fff", MODE="0660", GROUP="scanner", TAG+="uaccess"
# Raven Standard / Pro models
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="2fca", MODE="0660", GROUP="scanner", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="2fec", MODE="0660", GROUP="scanner", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="2f4a", MODE="0660", GROUP="scanner", TAG+="uaccess"
EOF

echo "2. Reloading udev rules..."
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb

echo "3. Checking SANE backend installation..."
if ! pacman -Q sane >/dev/null 2>&1; then
    echo "Installing sane package..."
    sudo pacman -S --noconfirm sane
fi

echo "4. Configuring /etc/sane.d/avision.conf for ALL supported scanner PIDs..."
if [ -d "/etc/sane.d" ]; then
    for PID in 0x3200 0x2fff 0x2fca 0x2fec 0x2f4a; do
        if ! grep -q "0x0638 $PID" "$AVISION_CONF" 2>/dev/null; then
            echo "usb 0x0638 $PID" | sudo tee -a "$AVISION_CONF" > /dev/null
        fi
    done
fi

echo ""
echo "✅ Permissions & udev rules installed successfully!"
echo "You can now run RavenScan without root permissions."
