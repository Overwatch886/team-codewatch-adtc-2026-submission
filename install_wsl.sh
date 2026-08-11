#!/usr/bin/env bash
# ==============================================================================
# WSL2 installer — compatibility shim
# ==============================================================================
# install_linux.sh now handles native Linux and WSL2 in a single script: it detects
# WSL from /proc/version, uses /dev/dxg for GPU passthrough detection, and prints
# the Windows-specific guidance at the end.
#
# This file is kept so existing instructions and bookmarks pointing at
# ./install_wsl.sh keep working. It simply forwards to the real installer.
# ==============================================================================
set -e

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "install_wsl.sh has been merged into install_linux.sh (it auto-detects WSL2)."
echo "Running $WORKSPACE_DIR/install_linux.sh ..."
echo

exec bash "$WORKSPACE_DIR/install_linux.sh" "$@"
