# Design Specification: codex-gateway

This document outlines the architecture, file layout, configuration design, and lifecycle management for `codex-gateway`, a self-contained local API gateway that bridges OpenAI's Codex Desktop application with Cloud DeepSeek APIs and standard local OpenAI-compatible runners (Ollama, LM Studio, vLLM, etc.).

## 1. Project Goal & Overview
The `codex-gateway` acts as a local proxy running on `http://127.0.0.1:8000`. It bridges Codex Desktop's proprietary **Responses API** (`wire_api = "responses"`) with standard `/v1/chat/completions` REST endpoints. 

Key features include:
*   **Multi-Backend Routing**: Dynamically routes API requests to either Cloud DeepSeek APIs or local model backends (Ollama, LM Studio, vLLM) based on model ID prefixes.
*   **Dynamic Model Catalog Aggregation**: Automatically queries active models from all enabled backends at startup and merges them into a unified catalog JSON file for Codex Desktop.
*   **R1 Thinking Stream Filtering**: Automatically parses and filters out `<think>...</think>` blocks for code-completion models (preventing parsing failures) and formats them into Markdown for chat models.
*   **Automatic Lifecycle Management**: Launches the local proxy, patches `~/.codex/config.toml` safely with backup protection, runs Codex Desktop, and cleanly terminates the proxy and restores configurations upon app exit.

## 2. Directory Structure
All components are organized locally within the workspace:

```text
codex-deepseek/ (referred to as codex-gateway)
├── .gitignore               # Ignores sensitive keys, virtual environment, and runtime configs
├── requirements.txt         # Minimal dependency definitions (fastapi, uvicorn, httpx)
├── gateway.sh               # Entrypoint orchestrator (venv prep, profiles setup, run & daemon cleanup)
├── gateway.env.example      # Environment configuration template
├── gateway.env              # Active local environment keys & backends configuration (git ignored)
├── config/                  # Dynamically generated catalog directory
│   └── model-catalog.json   # Unified model list aggregated from active cloud & local backends
└── engine/                  # Proxy adapter service source code
    ├── __init__.py
    ├── main.py              # Main FastAPI application, configuration loader, and catalog aggregator
    ├── parser.py            # Bidirectional protocol translator (Responses API <-> Chat Completions API)
    └── think_handler.py     # Stream filter for parsing/cleaning DeepSeek-R1 <think> blocks
```

## 3. Configuration Design (`gateway.env`)
The environment configuration contains standard variables to activate backends and provide API keys.

```bash
# =====================================================================
# 🚀 codex-gateway Runtime Configuration
# =====================================================================

# ----------------- [1. Base Server Settings] -----------------
GATEWAY_PORT=8000

# ----------------- [2. DeepSeek Cloud Settings] -----------------
ENABLE_DEEPSEEK=true
DEEPSEEK_API_KEY="sk-your-real-deepseek-key"
# Comma-separated list of default models to expose
DEEPSEEK_MODELS="deepseek-coder,deepseek-reasoner,deepseek-chat"

# ----------------- [3. Local Model Backend A (e.g., LM Studio / vLLM)] -----------------
ENABLE_LOCAL_A=false
LOCAL_A_NAME="lm-studio"
LOCAL_A_BASE_URL="http://localhost:1234/v1"

# ----------------- [4. Local Model Backend B (e.g., Ollama)] -----------------
ENABLE_LOCAL_B=false
LOCAL_B_NAME="ollama"
LOCAL_B_BASE_URL="http://localhost:11434/v1"
```

## 4. Architecture & Protocol Translation Flow
The proxy server intercepts Codex Desktop's calls and handles protocol conversion natively.

### A. Dynamic Catalog Aggregator
Upon startup, the python engine queries the `GET /v1/models` endpoint for each enabled local backend, appends appropriate prefixes (e.g., `lm-studio/`, `ollama/`), merges them with DeepSeek models, and writes the output to `config/model-catalog.json`:
```json
{
  "models": [
    {"id": "deepseek/deepseek-coder", "name": "DeepSeek Coder (Cloud)"},
    {"id": "deepseek/deepseek-reasoner", "name": "DeepSeek R1 (Cloud)"},
    {"id": "lm-studio/qwen2.5-coder-7b", "name": "Qwen 2.5 Coder 7B (Local)"}
  ]
}
```

### B. Request Dispatcher
When a chat or completion request arrives, `engine/main.py` parses the target model ID prefix:
1.  **`deepseek/*`**: Dispatched to `https://api.deepseek.com/v1`.
2.  **`lm-studio/*`**: Dispatched to `http://localhost:1234/v1`.
3.  **`ollama/*`**: Dispatched to `http://localhost:11434/v1`.

### C. Stream Converter & R1 Parser
For streaming requests, `parser.py` maps Codex SSE format to standard Server-Sent Events. Additionally, `think_handler.py` detects `<think>` and `</think>` tags:
*   **Discard Mode (Code Autocomplete)**: The text inside `<think>...</think>` is completely discarded. Only raw output is passed to Codex to avoid parsing bugs.
*   **Format Mode (Chat)**: The thinking block is extracted and enclosed in a Markdown collapsible block (e.g. `> [!NOTE]\n> 💭 Thinking process:\n> ...`) before being forwarded.

## 5. Lifecycle Management (`gateway.sh`)
The shell controller guarantees clean setups and execution:
1.  **Sandbox Isolation**: Checks for a local python `.venv` folder. Creates it and installs dependencies asynchronously if missing.
2.  **Configuration Injection**:
    *   Creates a backup of the original Codex configuration: `~/.codex/config.toml` -> `~/.codex/config.toml.codex_default_backup`.
    *   Appends/Injects the `codex-gateway` profile pointing to `http://127.0.0.1:8000/v1` and mapping the model catalog json.
3.  **Daemon & Cleanup**:
    *   Launches the FastAPI proxy server in the background.
    *   Launches Codex Desktop via native `/Applications/Codex.app/Contents/MacOS/Codex`.
    *   Blocks and listens. When Codex Desktop terminates, the script automatically kills the background Python proxy, restores the configuration backup, and terminates gracefully.
