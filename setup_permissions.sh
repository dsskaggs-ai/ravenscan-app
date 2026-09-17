#!/usr/bin/env bash
# ==============================================================================
# RavenScan - Scanner Permissions & System Setup for Omarchy / Arch Linux
# ==============================================================================

set -e

echo "=== Raven Scanner (Avision AD215W) Setup ==="
echo ""

UDEV_RULE_FILE="/etc/udev/rules.d/99-raven-scanner.rules"
AVISION_CONF="/etc/sane.d/avision.conf"

echo "1. Checking / Creating udev rules for Raven Scanner (VID 0638, PID 3200 / 2FFF)..."
sudo tee "$UDEV_RULE_FILE" > /dev/null << 'EOF'
# Raven Compact Scanner (Avision AD215W/AD215)
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="3200", MODE="0666", GROUP="scanner", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="2fff", MODE="0666", GROUP="scanner", TAG+="uaccess"
# Raven Standard / Pro models
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="2fca", MODE="0666", GROUP="scanner", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="2fec", MODE="0666", GROUP="scanner", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="2f4a", MODE="0666", GROUP="scanner", TAG+="uaccess"
EOF

echo "2. Reloading udev rules..."
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb

echo "3. Checking SANE backend installation..."
if ! pacman -Q sane >/dev/null 2>&1; then
    echo "Installing sane package..."
    sudo pacman -S --noconfirm sane
fi

if [ -d "/etc/sane.d" ]; then
    echo "Configuring /etc/sane.d/avision.conf..."
    if ! grep -q "0x0638 0x3200" "$AVISION_CONF" 2>/dev/null; then
        echo "usb 0x0638 0x3200" | sudo tee -a "$AVISION_CONF" > /dev/null
    fi
fi

echo ""
echo "✅ Permissions & udev rules installed successfully!"
echo "You can now run RavenScan without root permissions."
