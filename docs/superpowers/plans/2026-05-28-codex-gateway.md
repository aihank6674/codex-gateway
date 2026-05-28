# codex-gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a robust, self-contained local API gateway that bridges OpenAI's Codex Desktop application with Cloud DeepSeek APIs and standard local OpenAI-compatible APIs (LM Studio, Ollama, etc.), supporting dynamic model catalog aggregation and R1 thinking stream filtering.

**Architecture:** A local lightweight FastAPI server running in a virtual environment acts as a proxy translating Codex's "Responses API" to standard "Chat Completions". An orchestrator script handles environment prep, safe config patching/rollback, process daemonizing, and cleanup.

**Tech Stack:** Python 3 (FastAPI, Uvicorn, HTTPX), Bash.

---

## Technical File Mapping
*   **Create**: `requirements.txt` - Python project dependencies
*   **Create**: `.gitignore` - Workspace git exclusion configuration
*   **Create**: `gateway.env.example` - Template environment variables
*   **Create**: `engine/configurator.py` - TOML safe configuration patcher & rollback utility
*   **Create**: `engine/think_handler.py` - DeepSeek-R1 <think> tag stream filtering processor
*   **Create**: `engine/parser.py` - Responses API <-> Chat Completions API protocol translator
*   **Create**: `engine/main.py` - Core FastAPI proxy router & model catalog aggregator
*   **Create**: `gateway.sh` - Entrypoint script orchestrating environment, execution, and cleanup
*   **Create**: `tests/test_configurator.py` - Test suite for safe config patching
*   **Create**: `tests/test_think_handler.py` - Test suite for stream R1 think blocks parsing
*   **Create**: `tests/test_parser.py` - Test suite for protocol JSON translations

---

### Task 1: Project Boilerplate & Configuration Files

**Files:**
*   Create: `requirements.txt`
*   Create: `.gitignore`
*   Create: `gateway.env.example`
*   Create: `gateway.env`

- [ ] **Step 1: Create requirements.txt**
  Write dependencies for Python engine.
  ```text
  fastapi>=0.110.0
  uvicorn>=0.28.0
  httpx>=0.27.0
  python-dotenv>=1.0.1
  pytest>=8.0.0
  ```

- [ ] **Step 2: Create .gitignore**
  Write standard git ignores including python artifacts, virtual env, and secrets.
  ```text
  .venv/
  __pycache__/
  *.pyc
  gateway.env
  config/
  ```

- [ ] **Step 3: Create gateway.env.example**
  Write config template.
  ```bash
  # =====================================================================
  # codex-gateway Runtime Settings
  # =====================================================================
  GATEWAY_PORT=8000

  # DeepSeek Cloud settings
  ENABLE_DEEPSEEK=true
  DEEPSEEK_API_KEY="your-deepseek-api-key"
  DEEPSEEK_MODELS="deepseek-v4-flash,deepseek-v4-pro,deepseek-chat"

  # Local model backends
  ENABLE_LOCAL_A=false
  LOCAL_A_NAME="lm-studio"
  LOCAL_A_BASE_URL="http://localhost:1234/v1"

  ENABLE_LOCAL_B=false
  LOCAL_B_NAME="ollama"
  LOCAL_B_BASE_URL="http://localhost:11434/v1"
  ```

- [ ] **Step 4: Copy example config to gateway.env**
  Make sure a local development file is created without actual keys for safety.
  Run: `cp gateway.env.example gateway.env`
  Expected: `gateway.env` file exists.

- [ ] **Step 5: Commit task**
  Run:
  ```bash
  git add requirements.txt .gitignore gateway.env.example
  git commit -m "feat: add project boilerplate and env templates"
  ```

---

### Task 2: Safe TOML Configuration Patcher & Rollback Utility

**Files:**
*   Create: `engine/configurator.py`
*   Create: `tests/test_configurator.py`

- [ ] **Step 1: Write tests/test_configurator.py**
  Create robust TDD tests validating TOML parsing, patching, and rollback.
  ```python
  import os
  import tempfile
  from engine.configurator import patch_config, rollback_config

  def test_patch_and_rollback():
      with tempfile.NamedTemporaryFile(delete=False, suffix=".toml") as tmp:
          tmp.write(b"model_provider = \"openai\"\n\n[model_providers.openai]\nname = \"OpenAI\"\n")
          tmp_path = tmp.name

      try:
          # Patch
          patch_config(tmp_path, "http://127.0.0.1:8000/v1", "/tmp/catalog.json")
          with open(tmp_path, "r") as f:
              content = f.read()
          assert "model_provider = \"codex-gateway\"" in content
          assert "[model_providers.codex-gateway]" in content
          assert "base_url = \"http://127.0.0.1:8000/v1\"" in content

          # Rollback
          rollback_config(tmp_path)
          with open(tmp_path, "r") as f:
              content = f.read()
          assert "model_provider = \"openai\"" in content
          assert "codex-gateway" not in content
      finally:
          if os.path.exists(tmp_path):
              os.unlink(tmp_path)
          backup_path = tmp_path + ".codex_default_backup"
          if os.path.exists(backup_path):
              os.unlink(backup_path)
  ```

- [ ] **Step 2: Write engine/configurator.py**
  Implement safe TOML patching using built-in string/regex handling to avoid dependency issues on raw parsing.
  ```python
  import os
  import sys
  import shutil
  import re

  def patch_config(config_path, gateway_url, catalog_path):
      expanded_path = os.path.expanduser(config_path)
      backup_path = expanded_path + ".codex_default_backup"

      # Ensure config directory exists
      os.makedirs(os.path.dirname(expanded_path), exist_ok=True)

      # 1. Back up if not already done
      if not os.path.exists(backup_path):
          if os.path.exists(expanded_path):
              shutil.copy2(expanded_path, backup_path)
          else:
              with open(backup_path, "w") as f:
                  f.write("")

      # Read original
      content = ""
      if os.path.exists(expanded_path):
          with open(expanded_path, "r") as f:
              content = f.read()

      # Remove previous patch blocks if any
      content = re.sub(r"\n*# === START CODEX-GATEWAY ===.*# === END CODEX-GATEWAY ===\n*", "", content, flags=re.DOTALL)

      # Update default model_provider safely
      if "model_provider =" in content:
          content = re.sub(r"model_provider\s*=\s*\"[^\"]+\"", "model_provider = \"codex-gateway\"", content)
      else:
          content = "model_provider = \"codex-gateway\"\n" + content

      # Injected configuration
      patch_data = f"""
  # === START CODEX-GATEWAY ===
  [model_providers.codex-gateway]
  name = "Codex Gateway"
  base_url = "{gateway_url}"
  wire_api = "responses"
  model_catalog_json = "{catalog_path}"

  [profiles.codex-gateway]
  model_provider = "codex-gateway"
  # === END CODEX-GATEWAY ===
  """
      new_content = content.strip() + "\n" + patch_data

      with open(expanded_path, "w") as f:
          f.write(new_content)
      print(f"[configurator] Patched {config_path} successfully.")

  def rollback_config(config_path):
      expanded_path = os.path.expanduser(config_path)
      backup_path = expanded_path + ".codex_default_backup"

      if os.path.exists(backup_path):
          shutil.copy2(backup_path, expanded_path)
          os.unlink(backup_path)
          print(f"[configurator] Rolled back {config_path} to original state.")
      else:
          print(f"[configurator] No backup found to restore.")

  if __name__ == "__main__":
      if len(sys.argv) < 3:
          print("Usage: configurator.py --patch <config_path> <gateway_url> <catalog_path> | --rollback <config_path>")
          sys.exit(1)
      
      mode = sys.argv[1]
      target = sys.argv[2]
      if mode == "--patch":
          patch_config(target, sys.argv[3], sys.argv[4])
      elif mode == "--rollback":
          rollback_config(target)
  ```

- [ ] **Step 3: Run pytest on configurator**
  Run: `pytest tests/test_configurator.py -v`
  Expected: PASS

- [ ] **Step 4: Commit task**
  Run:
  ```bash
  git add engine/configurator.py tests/test_configurator.py
  git commit -m "feat: implement configuration patcher and rollback utility with test"
  ```

---

### Task 3: Stream R1 Think Tag Filtering Engine

**Files:**
*   Create: `engine/think_handler.py`
*   Create: `tests/test_think_handler.py`

- [ ] **Step 1: Write tests/test_think_handler.py**
  Create unit tests validating stream chunks filtering for code and chat.
  ```python
  from engine.think_handler import ThinkStreamFilter

  def test_discard_think_blocks():
      stream_filter = ThinkStreamFilter(discard_think=True)
      chunks = ["Hello ", "<think>", "analyzing ", "code ", "</think>", "world!"]
      results = []
      for chunk in chunks:
          out = stream_filter.process(chunk)
          if out:
              results.append(out)
      assert "".join(results) == "Hello world!"

  def test_format_think_blocks():
      stream_filter = ThinkStreamFilter(discard_think=False)
      chunks = ["Start ", "<think>", "brainstorm", "</think>", " End"]
      results = []
      for chunk in chunks:
          out = stream_filter.process(chunk)
          if out:
              results.append(out)
      
      full_output = "".join(results)
      assert "Start " in full_output
      assert "> 💭 *Thinking process:*" in full_output
      assert "brainstorm" in full_output
      assert " End" in full_output
  ```

- [ ] **Step 2: Write engine/think_handler.py**
  Implement the streaming parser tracking state (`in_think = True/False`).
  ```python
  class ThinkStreamFilter:
      def __init__(self, discard_think=True):
          self.discard_think = discard_think
          self.in_think = False
          self.buffer = ""

      def process(self, chunk: str) -> str:
          self.buffer += chunk
          output = []

          while self.buffer:
              if not self.in_think:
                  # Look for start tag
                  idx = self.buffer.find("<think>")
                  if idx != -1:
                      # Output anything before <think>
                      output.append(self.buffer[:idx])
                      self.in_think = True
                      if not self.discard_think:
                          output.append("\n> [!NOTE]\n> 💭 *Thinking process:*\n> ")
                      self.buffer = self.buffer[idx + len("<think>"):]
                  else:
                      # If partial tag <thin... is at the end, wait
                      potential_start = "<think>"
                      matched_len = 0
                      for i in range(1, len(potential_start)):
                          if self.buffer.endswith(potential_start[:i]):
                              matched_len = i
                              break
                      if matched_len > 0:
                          output.append(self.buffer[:-matched_len])
                          self.buffer = self.buffer[-matched_len:]
                          break
                      else:
                          output.append(self.buffer)
                          self.buffer = ""
              else:
                  # Inside think block, look for end tag
                  idx = self.buffer.find("</think>")
                  if idx != -1:
                      think_content = self.buffer[:idx]
                      if not self.discard_think:
                          # Format thinking content by prefixing each line with >
                          formatted = think_content.replace("\n", "\n> ")
                          output.append(formatted + "\n\n")
                      self.in_think = False
                      self.buffer = self.buffer[idx + len("</think>"):]
                  else:
                      # If partial tag </thin... is at the end, wait
                      potential_end = "</think>"
                      matched_len = 0
                      for i in range(1, len(potential_end)):
                          if self.buffer.endswith(potential_end[:i]):
                              matched_len = i
                              break
                      if matched_len > 0:
                          in_block = self.buffer[:-matched_len]
                          if not self.discard_think:
                              output.append(in_block.replace("\n", "\n> "))
                          self.buffer = self.buffer[-matched_len:]
                          break
                      else:
                          if not self.discard_think:
                              output.append(self.buffer.replace("\n", "\n> "))
                          self.buffer = ""
                          break

          return "".join(output)
  ```

- [ ] **Step 3: Run pytest on think_handler**
  Run: `pytest tests/test_think_handler.py -v`
  Expected: PASS

- [ ] **Step 4: Commit task**
  Run:
  ```bash
  git add engine/think_handler.py tests/test_think_handler.py
  git commit -m "feat: add streaming R1 think tag parsing engine with tests"
  ```

---

### Task 4: Protocol Translator (Responses API <-> Chat Completions)

**Files:**
*   Create: `engine/parser.py`
*   Create: `tests/test_parser.py`

- [ ] **Step 1: Write tests/test_parser.py**
  Write tests validating request payload mapping and stream formats translation.
  ```python
  from engine.parser import transform_request, transform_response_chunk

  def test_request_payload_transformation():
      codex_req = {
          "model": "deepseek/deepseek-v4-flash",
          "prompt": "def add(a, b):",
          "max_tokens": 100,
          "stream": True
      }
      openai_req = transform_request(codex_req, "deepseek-v4-flash")
      assert openai_req["model"] == "deepseek-v4-flash"
      assert openai_req["messages"][0]["role"] == "user"
      assert openai_req["messages"][0]["content"] == "def add(a, b):"
      assert openai_req["stream"] is True

  def test_chunk_response_transformation():
      openai_chunk = {
          "choices": [
              {
                  "delta": {"content": "return a + b"},
                  "finish_reason": None
              }
          ]
      }
      codex_chunk = transform_response_chunk(openai_chunk, "deepseek/deepseek-v4-flash")
      assert codex_chunk["choices"][0]["text"] == "return a + b"
      assert codex_chunk["choices"][0]["finish_reason"] is None
  ```

- [ ] **Step 2: Write engine/parser.py**
  Implement protocol translations.
  ```python
  def transform_request(codex_payload: dict, actual_model: str) -> dict:
      # Map Codex prompt structure to standard Chat messages
      prompt = codex_payload.get("prompt", "")
      
      # Try extracting standard format if prompt is structured, otherwise wrap as user prompt
      messages = [{"role": "user", "content": prompt}]
      
      # Handle optional agent history conversion if system instruction or context is passed
      if "system" in codex_payload:
          messages.insert(0, {"role": "system", "content": codex_payload["system"]})

      transformed = {
          "model": actual_model,
          "messages": messages,
          "temperature": codex_payload.get("temperature", 0.2),
          "max_tokens": codex_payload.get("max_tokens", 1024),
          "top_p": codex_payload.get("top_p", 1.0),
          "stream": codex_payload.get("stream", False)
      }
      return transformed

  def transform_response_chunk(openai_chunk: dict, original_model_id: str) -> dict:
      # Maps standard chat completions chunk back to Responses format
      choices = []
      for choice in openai_chunk.get("choices", []):
          delta = choice.get("delta", {})
          text = delta.get("content", "")
          choices.append({
              "text": text,
              "index": choice.get("index", 0),
              "finish_reason": choice.get("finish_reason", None)
          })
      
      return {
          "id": openai_chunk.get("id", "chatcmpl-local"),
          "object": "text_completion.chunk",
          "created": openai_chunk.get("created", 0),
          "model": original_model_id,
          "choices": choices
      }

  def transform_full_response(openai_res: dict, original_model_id: str) -> dict:
      # Maps non-streaming completions response back
      choices = []
      for choice in openai_res.get("choices", []):
          msg = choice.get("message", {})
          text = msg.get("content", "")
          choices.append({
              "text": text,
              "index": choice.get("index", 0),
              "finish_reason": choice.get("finish_reason", "stop")
          })
      
      return {
          "id": openai_res.get("id", "chatcmpl-local"),
          "object": "text_completion",
          "created": openai_res.get("created", 0),
          "model": original_model_id,
          "choices": choices
      }
  ```

- [ ] **Step 3: Run pytest on parser**
  Run: `pytest tests/test_parser.py -v`
  Expected: PASS

- [ ] **Step 4: Commit task**
  Run:
  ```bash
  git add engine/parser.py tests/test_parser.py
  git commit -m "feat: implement Responses protocol parser with tests"
  ```

---

### Task 5: Core Proxy Router & Catalog Aggregator

**Files:**
*   Create: `engine/main.py`

- [ ] **Step 1: Write engine/main.py**
  Implement core server and aggregator endpoints.
  ```python
  import os
  import json
  import httpx
  import asyncio
  from fastapi import FastAPI, Request, HTTPException
  from fastapi.responses import StreamingResponse
  from dotenv import load_dotenv

  from engine.parser import transform_request, transform_response_chunk, transform_full_response
  from engine.think_handler import ThinkStreamFilter

  load_dotenv("gateway.env")

  app = FastAPI(title="Codex Hybrid API Gateway")

  # Global HTTP client
  client = httpx.AsyncClient(timeout=60.0)

  # Load configurations
  ENABLE_DEEPSEEK = os.getenv("ENABLE_DEEPSEEK", "true").lower() == "true"
  DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
  DEEPSEEK_MODELS_RAW = os.getenv("DEEPSEEK_MODELS", "deepseek-v4-flash,deepseek-v4-pro")
  DEEPSEEK_MODELS = [m.strip() for m in DEEPSEEK_MODELS_RAW.split(",") if m.strip()]

  LOCAL_BACKENDS = []
  for prefix in ["LOCAL_A", "LOCAL_B"]:
      if os.getenv(f"ENABLE_{prefix}", "false").lower() == "true":
          LOCAL_BACKENDS.append({
              "name": os.getenv(f"{prefix}_NAME", prefix.lower()),
              "url": os.getenv(f"{prefix}_BASE_URL", ""),
          })

  @app.on_event("startup")
  async def aggregate_catalog():
      print("[catalog] Starting multi-backend model aggregation...")
      catalog = {"models": []}

      # 1. Load Cloud DeepSeek
      if ENABLE_DEEPSEEK:
          for model in DEEPSEEK_MODELS:
              name_suffix = "Reasoner (R1)" if "reasoner" in model else "Coder"
              catalog["models"].append({
                  "id": f"deepseek/{model}",
                  "name": f"DeepSeek {name_suffix} (Cloud)"
              })

      # 2. Query Local Backends
      for backend in LOCAL_BACKENDS:
          try:
              res = await client.get(f"{backend['url']}/models", timeout=3.0)
              if res.status_code == 200:
                  data = res.json()
                  models = data.get("data", []) or data.get("models", [])
                  # Handle diverse return formats of standard OpenAI compatible servers
                  for m in models:
                      model_id = m.get("id") if isinstance(m, dict) else m
                      catalog["models"].append({
                          "id": f"{backend['name']}/{model_id}",
                          "name": f"{model_id} ({backend['name'].upper()} Local)"
                      })
          except Exception as e:
              print(f"[catalog] Failed querying local backend {backend['name']}: {e}")

      # Output catalog to dynamic folder
      os.makedirs("config", exist_ok=True)
      with open("config/model-catalog.json", "w") as f:
          json.dump(catalog, f, indent=2)
      print(f"[catalog] Catalog aggregated successfully with {len(catalog['models'])} models.")

  @app.post("/v1/responses")
  async def handle_responses(request: Request):
      codex_req = await request.json()
      model_id = codex_req.get("model", "")

      # Determine target backend and target model
      target_backend = None
      target_model = ""

      if model_id.startswith("deepseek/"):
          target_backend = {"name": "deepseek", "url": "https://api.deepseek.com/v1"}
          target_model = model_id.replace("deepseek/", "")
      else:
          for b in LOCAL_BACKENDS:
              prefix = f"{b['name']}/"
              if model_id.startswith(prefix):
                  target_backend = b
                  target_model = model_id.replace(prefix, "")
                  break

      if not target_backend:
          raise HTTPException(status_code=400, detail=f"Unsupported model provider routing: {model_id}")

      # Transform request payload
      transformed = transform_request(codex_req, target_model)

      # Build headers
      headers = {"Content-Type": "application/json"}
      if target_backend["name"] == "deepseek":
          headers["Authorization"] = f"Bearer {DEEPSEEK_KEY}"

      # Streaming Logic
      if transformed.get("stream", False):
          async def stream_generator():
              async with client.stream(
                  "POST",
                  f"{target_backend['url']}/chat/completions",
                  json=transformed,
                  headers=headers
              ) as r:
                  if r.status_code != 200:
                      yield f"data: {json.dumps({'error': 'Backend error'})}\n\n"
                      return

                  # Determine whether R1 thinking filter should be engaged (code models discard, chat retains)
                  discard_think = "reasoner" not in target_model
                  stream_filter = ThinkStreamFilter(discard_think=discard_think)

                  async for line in r.iter_lines():
                      if not line:
                          continue
                      if line.startswith("data: "):
                          line_content = line[6:]
                          if line_content.strip() == "[DONE]":
                              yield "data: [DONE]\n\n"
                              continue
                          try:
                              openai_chunk = json.loads(line_content)
                              codex_chunk = transform_response_chunk(openai_chunk, model_id)
                              
                              # Process R1 think streams
                              if codex_chunk["choices"] and codex_chunk["choices"][0]["text"]:
                                  raw_text = codex_chunk["choices"][0]["text"]
                                  filtered_text = stream_filter.process(raw_text)
                                  codex_chunk["choices"][0]["text"] = filtered_text

                              yield f"data: {json.dumps(codex_chunk)}\n\n"
                          except Exception:
                              pass

          return StreamingResponse(stream_generator(), media_type="text/event-stream")
      
      # Non-Streaming Logic
      else:
          try:
              res = await client.post(
                  f"{target_backend['url']}/chat/completions",
                  json=transformed,
                  headers=headers
              )
              if res.status_code != 200:
                  raise HTTPException(status_code=res.status_code, detail="Upstream returned error")
              
              openai_res = res.json()
              codex_res = transform_full_response(openai_res, model_id)
              return codex_res
          except Exception as e:
              raise HTTPException(status_code=500, detail=str(e))

  if __name__ == "__main__":
      import uvicorn
      uvicorn.run(app, host="127.0.0.1", port=8000)
  ```

- [ ] **Step 2: Commit task**
  Run:
  ```bash
  git add engine/main.py
  git commit -m "feat: implement main FastAPI router and catalog aggregator"
  ```

---

### Task 6: Master Orchestrator Launcher Script

**Files:**
*   Create: `gateway.sh`

- [ ] **Step 1: Write gateway.sh**
  Create orchestrator handling virtual environments, configuration setups, running the app daemon, launching Codex Desktop, and executing traps.
  ```bash
  #!/bin/bash

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  CONFIG_TOML="$HOME/.codex/config.toml"
  CATALOG_JSON="$SCRIPT_DIR/config/model-catalog.json"
  GATEWAY_URL="http://127.0.0.1:8000/v1"

  # Exit immediately if key is missing
  if [ ! -f "$SCRIPT_DIR/gateway.env" ]; then
      echo "[gateway] ERROR: gateway.env missing! Please define your variables."
      exit 1
  fi

  source "$SCRIPT_DIR/gateway.env"
  if [ "$ENABLE_DEEPSEEK" = "true" ] && [ -z "$DEEPSEEK_API_KEY" ]; then
      echo "[gateway] ERROR: DEEPSEEK_API_KEY is empty in gateway.env!"
      exit 1
  fi

  # 1. Environment Sandbox Setup
  if [ ! -d "$SCRIPT_DIR/.venv" ]; then
      echo "[gateway] Preparing python virtual environment..."
      python3 -m venv "$SCRIPT_DIR/.venv"
      "$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip
      "$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
  fi

  # 2. Terminate previous processes if hanging
  lsof -i :8000 -t | xargs kill -9 2>/dev/null

  # 3. Patch Codex Profiles safely
  echo "[gateway] Safe patching ~/.codex/config.toml..."
  "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/engine/configurator.py" --patch "$CONFIG_TOML" "$GATEWAY_URL" "$CATALOG_JSON"

  # 4. Start local proxy in background
  echo "[gateway] Launching API Proxy Daemon..."
  "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/engine/main.py" > /dev/null 2>&1 &
  PROXY_PID=$!

  # Function to execute on exit
  cleanup() {
      echo "[gateway] Cleaning up and restoring profile configurations..."
      kill -9 "$PROXY_PID" 2>/dev/null
      "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/engine/configurator.py" --rollback "$CONFIG_TOML"
      echo "[gateway] Cleanup completed. Goodbye!"
  }

  # Hook up trap exits
  trap cleanup EXIT INT TERM

  # Wait a second for aggregator to output catalog.json
  sleep 1.5

  # 5. Launch Codex Desktop App
  echo "[gateway] Waking up Codex Desktop Application..."
  if [ -d "/Applications/Codex.app" ]; then
      /Applications/Codex.app/Contents/MacOS/Codex
  else
      echo "[gateway] ERROR: Codex.app not found in /Applications!"
      exit 1
  fi
  ```

- [ ] **Step 2: Make gateway.sh executable**
  Run: `chmod +x gateway.sh`
  Expected: Execution permission granted.

- [ ] **Step 3: Commit orchestrator**
  Run:
  ```bash
  git add gateway.sh
  git commit -m "feat: implement gateway orchestrator entrypoint"
  ```

---

## Plan Review & Handoff
Plan complete and saved to `docs/superpowers/plans/2026-05-28-codex-gateway.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
