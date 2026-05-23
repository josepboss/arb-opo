#!/usr/bin/env bash
# Convenience script to run the arbitrage engine locally (without Docker).
# Make sure you have Python 3.12+ and the dependencies installed:
#   pip install -r requirements.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Multi-Marketplace Arbitrage Engine ==="
echo ""

# Ensure dependencies are installed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "[+] Installing dependencies..."
    pip install -r requirements.txt
fi

# Run the main entry point
echo "[+] Starting engine..."
python main.py