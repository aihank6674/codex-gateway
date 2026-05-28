# codex-gateway 🚀

[![Build Status](https://img.shields.io/badge/tests-8%20passed-brightgreen.svg)](https://github.com/aihank6674/codex-gateway)
[![Python Version](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A self-contained, light-speed local API gateway that bridges **OpenAI's Codex Desktop** application with **Cloud DeepSeek APIs** and standard **local OpenAI-compatible model runners** (LM Studio, Ollama, vLLM, llama.cpp, etc.). 

By translating proprietary Codex "Responses API" payloads into standard "Chat Completions" REST endpoints, `codex-gateway` provides a unified portal to run cloud reasoning models and local code-completion engines simultaneously inside your Codex GUI.

---

## 🎨 Dual-Channel Architecture

```mermaid
graph TD
    A[Codex Desktop GUI] -->|Proprietary Responses API| B[Local codex-gateway :8761]
    
    B -->|Prefix Parsing & Dispatching| C{Backend Router}
    
    B -->|GET /v1/models| K[Dynamic Models Aggregator]
    K -->|Aggregate Active Catalog| A
    
    C -->|deepseek/*| D[Cloud DeepSeek API]
    C -->|lm-studio/*| E[Local LM Studio Engine]
    C -->|ollama/*| F[Local Ollama Runner]
    
    D -->|R1 Stream Tag Parser| G[Think Stream Filter]
    E --> H[Standard Stream Proxy]
    F --> H
    
    G -->|Autocomplete: Discard Tags<br>Chat: Format to Collapsible MD| I[Responses Payload Stream]
    H --> I
    
    I -->| SSE Stream Back| A
```

---

## ✨ Key Features

*   **☁️ Cloud & 🏠 Local Hybrid Routing**: Effortlessly toggle between full-scale cloud models (DeepSeek V3, R1) and local private completion engines (Qwen2.5-Coder, Llama-3) directly in the Codex Desktop dropdown without restarting.
*   **🔍 Dynamic Model Aggregation**: On startup, the gateway concurrently queries all enabled local backends, merges active models with your DeepSeek cloud roster, and dynamically generates Codex's `model-catalog.json` for UI rendering.
*   **🧠 DeepSeek-R1 Stream Beautifier**: Automatically parses R1's `<think>...</think>` tags on the fly:
    *   *Code Autocomplete*: Completely discards the thinking text to prevent editor parser failures.
    *   *Agent Chat*: Beautifies the thinking stream into clean, collapsible Markdown blocks so you can follow the model's reasoning without cluttering the canvas.
*   **🔄 Safe Profile Injection & Rollback**: Safe, idempotent config patching for `~/.codex/config.toml` that backs up your environment on launch and completely restores it upon application exit.
*   **🛡️ Lifecycle Daemon**: A simple execution wrapper script (`gateway.sh`) handles setting up an isolated virtual python environment, launching the proxy server, waking up Codex, and guaranteeing clean process terminations.

## 🎭 UI Limitations & Model Mapping (Important!)

Due to internal design choices in the official Codex Desktop application (specifically its proprietary `responses` API), **the model selection dropdown in the Codex UI is strictly hardcoded to official GPT models**. Codex Desktop will actively ignore `model_catalog_json` configurations and force the display of models like `GPT-5.5` and `GPT-5.4-Mini`.

Because we cannot natively inject custom dropdown menus into the closed-source Codex client without losing advanced features, `codex-gateway` utilizes a silent **fallback routing mapping**. 

You should select models in the UI based on this predefined tier mapping:

| UI Selection (The "Mask") | Backend Routing (The "Reality") | Target Tier |
| :--- | :--- | :--- |
| **`GPT-5.5`** | **DeepSeek Pro Reasoning** (or other high-tier models) | High-Tier / Heavy Reasoning |
| **`GPT-5.4` / `GPT-5.4-Mini`** | **DeepSeek Flash** (or other low-tier models) | Low-Tier / Fast Autocomplete |

*Note: The gateway handles this translation automatically. Simply select the desired GPT tier in the UI, and the gateway will silently route your request to the appropriate DeepSeek or local model.*

---

## 🚀 Quick Start

### 1. Prerequisite
Ensure you have **Python 3** and **Codex Desktop** installed on your macOS machine.

### 2. Setup Configuration
Clone the repository, copy the example environment template, and insert your DeepSeek API Key:
```bash
git clone https://github.com/aihank6674/codex-gateway.git
cd codex-gateway

# Copy template configuration
cp gateway.env.example gateway.env

# Open and add your DeepSeek API Key
nano gateway.env
```

### 3. Run the Launcher
Simply start the gateway orchestrator:
```bash
./gateway.sh
```
*The script will automatically set up its own isolated virtual environment (`.venv`), patch your profile, launch the proxy server, and wake up Codex Desktop!*

---

## ⚙️ Configuration Parameters (`gateway.env`)

Configure gateways dynamically to aggregate cloud and local endpoints:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `GATEWAY_PORT` | `8761` | Local gateway proxy execution port. |
| `ENABLE_DEEPSEEK` | `true` | Set to true to activate Cloud DeepSeek routes. |
| `DEEPSEEK_API_KEY` | `""` | Your official DeepSeek API credentials. |
| `DEEPSEEK_MODELS` | `deepseek-coder,deepseek-reasoner` | Comma-separated cloud models to expose in the picker. |
| `ENABLE_LOCAL_A` | `false` | Enable/Disable local runner A (e.g. LM Studio, vLLM). |
| `LOCAL_A_NAME` | `"lm-studio"` | Model ID prefix for backend A (e.g. `lm-studio/model-id`). |
| `LOCAL_A_BASE_URL` | `"http://localhost:1234/v1"` | Port address where backend A is running. |
| `ENABLE_LOCAL_B` | `false` | Enable/Disable local runner B (e.g. Ollama). |
| `LOCAL_B_NAME` | `"ollama"` | Model ID prefix for backend B. |
| `LOCAL_B_BASE_URL` | `"http://localhost:11434/v1"` | Port address where backend B is running. |

---

## 🧪 Developer & TDD Testing

`codex-gateway` is designed with strict Test-Driven Development (TDD). You can run the entire test suite locally to verify protocol parser, stream tag matching, and config patching safety:

```bash
# Setup virtual environment and dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run pytest suite
pytest tests/ -v
```

### Passing Tests Output:
```text
tests/test_configurator.py::test_patch_and_rollback PASSED               [ 12%]
tests/test_parser.py::test_request_payload_transformation PASSED         [ 25%]
tests/test_parser.py::test_chunk_response_transformation PASSED          [ 37%]
tests/test_parser.py::test_full_response_transformation PASSED           [ 50%]
tests/test_parser.py::test_request_input_array_transformation PASSED     [ 62%]
tests/test_think_handler.py::test_discard_think_blocks PASSED            [ 75%]
tests/test_think_handler.py::test_format_think_blocks PASSED             [ 87%]
tests/test_think_handler.py::test_partial_tag_buffering PASSED           [100%]

============================== 8 passed in 0.03s ===============================
```

---

## 📄 License
Distributed under the MIT License. See `LICENSE` for more information.
