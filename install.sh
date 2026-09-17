#!/usr/bin/env bash
# ==============================================================================
# Installer for Raven Desktop on Omarchy / Linux
# ==============================================================================

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/128x128/apps"
DATA_DIR="$HOME/.local/share/ravenscan"

echo "=== Installing Raven Desktop ==="

# 1. Ensure target directories exist
mkdir -p "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR" "$DATA_DIR"

# 2. Install application icon
echo "Installing application icon..."
cp "$APP_DIR/assets/icon.png" "$ICON_DIR/ravenscan.png"

# 3. Install binary launcher
echo "Installing launcher into $BIN_DIR/ravenscan..."
cat << EOF > "$BIN_DIR/ravenscan"
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR:\$PYTHONPATH"
exec python3 "$APP_DIR/bin/ravenscan" "\$@"
EOF
chmod +x "$BIN_DIR/ravenscan"

# 4. Install permission helper script
echo "Installing setup script into $DATA_DIR/setup_permissions.sh..."
cp "$APP_DIR/setup_permissions.sh" "$DATA_DIR/setup_permissions.sh"
chmod +x "$DATA_DIR/setup_permissions.sh"

# 5. Install desktop file
echo "Installing desktop launcher into $DESKTOP_DIR/ravenscan.desktop..."
cp "$APP_DIR/ravenscan.desktop" "$DESKTOP_DIR/ravenscan.desktop"

# 6. Update desktop database
if which update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo ""
echo "✅ Raven Desktop installed successfully!"
echo "You can launch it from:"
echo "  1. Omarchy Application Menu (Super key -> Raven Desktop)"
echo "  2. Terminal: ravenscan"
