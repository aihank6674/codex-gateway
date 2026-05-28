#!/bin/bash

# =====================================================================
# 🚀 codex-gateway Orchestrator
# =====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_TOML="$HOME/.codex/config.toml"
CATALOG_JSON="$SCRIPT_DIR/config/model-catalog.json"
GATEWAY_URL="http://127.0.0.1:8000/v1"

echo "====================================================="
echo "      🚀 Waking up codex-gateway Environment         "
echo "====================================================="

# 1. Validation check for environment keys
if [ ! -f "$SCRIPT_DIR/gateway.env" ]; then
    echo "[gateway] ERROR: gateway.env missing!"
    echo "Please configure your API keys in gateway.env first."
    exit 1
fi

source "$SCRIPT_DIR/gateway.env"

if [ "$ENABLE_DEEPSEEK" = "true" ] && [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "[gateway] ERROR: DEEPSEEK_API_KEY is not defined in gateway.env!"
    echo "Please open gateway.env and fill in your DeepSeek API key."
    exit 1
fi

# 2. Setup Python isolated sandboxed environment
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "[gateway] Preparing isolated Python virtual environment (.venv)..."
    python3 -m venv "$SCRIPT_DIR/.venv"
    "$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip
    "$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
    echo "[gateway] Dependencies installed successfully."
fi

# 3. Clean up any previous dangling process on port 8000
echo "[gateway] Guaranteeing port 8000 is clean..."
lsof -i :8000 -t | xargs kill -9 2>/dev/null

# 4. Safe inject profile and provider into config.toml
echo "[gateway] Safely backing up and patching ~/.codex/config.toml..."
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/engine/configurator.py" --patch "$CONFIG_TOML" "$GATEWAY_URL" "$CATALOG_JSON"

# 5. Spin up Python Proxy Daemon in background
echo "[gateway] Launching local API Gateway Proxy Daemon on port 8000..."
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/engine/main.py" > /dev/null 2>&1 &
PROXY_PID=$!

# Define cleanup function to rollback profile injection and kill proxy daemon on exit
cleanup() {
    echo ""
    echo "[gateway] Performing clean exit..."
    echo "[gateway] Restoring original Codex config.toml configurations..."
    "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/engine/configurator.py" --rollback "$CONFIG_TOML"
    
    echo "[gateway] Terminating local API Gateway Proxy (PID $PROXY_PID)..."
    kill -9 "$PROXY_PID" 2>/dev/null
    echo "[gateway] Teardown complete. Have a great day!"
}

# Hook up exit signals to cleanup function
trap cleanup EXIT INT TERM

# Wait for aggregator to complete API queries and generate config/model-catalog.json
echo "[gateway] Waiting for backend catalog query aggregation..."
sleep 2.0

# 6. Launch Codex Desktop App via native executable bundle path to ensure ENV inheritance
echo "[gateway] Launching Codex Desktop App..."
if [ -d "/Applications/Codex.app" ]; then
    # Start app inside terminal shell so that it inherits current shell environment variables
    # This keeps the shell script alive until the user quits Codex Desktop.
    /Applications/Codex.app/Contents/MacOS/Codex
else
    echo "[gateway] ERROR: Codex.app was not found in /Applications!"
    echo "Please ensure Codex Desktop is installed at /Applications/Codex.app."
    exit 1
fi
