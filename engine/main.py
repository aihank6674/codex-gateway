import os
import sys
import json
import httpx
import asyncio

# Resolve project root (parent of engine/) so all paths work regardless of CWD
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from dotenv import load_dotenv

from engine.parser import transform_request, transform_response_chunk, transform_full_response
from engine.think_handler import ThinkStreamFilter
from engine.stats import record_request, get_stats
from engine.dashboard import DASHBOARD_HTML

# Load configurations from gateway.env (use absolute path so it works from any CWD)
CATALOG_PATH = os.path.join(PROJECT_ROOT, "config", "model-catalog.json")
load_dotenv(os.path.join(PROJECT_ROOT, "gateway.env"))

app = FastAPI(title="Codex Hybrid API Gateway")

# Global HTTP async client
client = httpx.AsyncClient(timeout=60.0)

# 1. Read Cloud DeepSeek settings
ENABLE_DEEPSEEK = os.getenv("ENABLE_DEEPSEEK", "true").lower() == "true"
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODELS_RAW = os.getenv("DEEPSEEK_MODELS", "deepseek-v4-flash,deepseek-v4-pro")
DEEPSEEK_MODELS = [m.strip() for m in DEEPSEEK_MODELS_RAW.split(",") if m.strip()]

# 2. Read Local Backend settings
LOCAL_BACKENDS = []
for prefix in ["LOCAL_A", "LOCAL_B"]:
    if os.getenv(f"ENABLE_{prefix}", "false").lower() == "true":
        LOCAL_BACKENDS.append({
            "name": os.getenv(f"{prefix}_NAME", prefix.lower()),
            "url": os.getenv(f"{prefix}_BASE_URL", ""),
        })

@app.on_event("startup")
async def aggregate_catalog():
    """
    Executes on application startup. Discovers active models from all active
    cloud and local backends and outputs a unified config/model-catalog.json
    so that Codex Desktop displays them in the UI.
    """
    print("[catalog] Starting multi-backend model catalog aggregation...")
    catalog = {"models": []}

    # Integrate Cloud DeepSeek models
    if ENABLE_DEEPSEEK:
        for model in DEEPSEEK_MODELS:
            name_suffix = "Reasoner (R1)" if "reasoner" in model or "pro" in model else "Coder"
            if model == "deepseek-chat":
                name_suffix = "General Chat (V3)"
            elif model == "deepseek-v4-flash":
                name_suffix = "Flash (V4)"
            elif model == "deepseek-v4-pro":
                name_suffix = "Pro Reasoning (V4)"
            catalog["models"].append({
                "id": f"deepseek/{model}",
                "name": f"DeepSeek {name_suffix} (Cloud)"
            })

    # Query active models from standard local OpenAI-compatible backends
    for backend in LOCAL_BACKENDS:
        try:
            res = await client.get(f"{backend['url']}/models", timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                models_data = data.get("data", []) or data.get("models", [])
                
                for m in models_data:
                    model_id = m.get("id") if isinstance(m, dict) else m
                    catalog["models"].append({
                        "id": f"{backend['name']}/{model_id}",
                        "name": f"{model_id} ({backend['name'].upper()} Local)"
                    })
                print(f"[catalog] Successfully loaded models from local backend: {backend['name']}")
        except Exception as e:
            print(f"[catalog] Warning: Failed querying local backend '{backend['name']}': {e}")

    # Write output to dynamic directory
    os.makedirs(os.path.join(PROJECT_ROOT, "config"), exist_ok=True)
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)
    
    print(f"[catalog] Completed. Unified catalog contains {len(catalog['models'])} models.")

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the real-time monitoring dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/v1/stats")
async def stats_endpoint():
    """Return current proxy stats as JSON for dashboard auto-refresh."""
    return JSONResponse(content=get_stats())


@app.get("/v1/models")
async def list_models():
    """
    Returns the custom models catalog dynamically from our unified model aggregated lists.
    """
    models_list = []
    if os.path.exists(CATALOG_PATH):
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                catalog = json.load(f)
                for m in catalog.get("models", []):
                    models_list.append({
                        "id": m.get("id"),
                        "object": "model",
                        "created": 1677649420,
                        "owned_by": m.get("id").split("/")[0] if "/" in m.get("id") else "custom"
                    })
        except Exception:
            pass
            
    if not models_list:
        if ENABLE_DEEPSEEK:
            for model in DEEPSEEK_MODELS:
                models_list.append({
                    "id": f"deepseek/{model}",
                    "object": "model",
                    "created": 1677649420,
                    "owned_by": "deepseek"
                })
                
    return {
        "object": "list",
        "data": models_list
    }

@app.post("/v1/responses")
async def handle_responses(request: Request):
    """
    Main proxy endpoint intercepting Codex Responses API calls.
    Performs prefix-based model routing, translates requests, and returns
    SSE streaming or full JSON payloads back.
    """
    try:
        codex_payload = await request.json()
        print(f"[gateway] Incoming request: {json.dumps(codex_payload)}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    model_id = codex_payload.get("model", "")
    if not model_id:
        raise HTTPException(status_code=400, detail="Model parameter is missing.")

    # Prefix-based routing resolution
    target_backend = None
    target_model = ""

    if model_id.startswith("deepseek/"):
        target_backend = {
            "name": "deepseek",
            "url": "https://api.deepseek.com/v1"
        }
        target_model = model_id.replace("deepseek/", "")
    else:
        # Match configured local backends
        for b in LOCAL_BACKENDS:
            prefix = f"{b['name']}/"
            if model_id.startswith(prefix):
                target_backend = b
                target_model = model_id.replace(prefix, "")
                break

    if not target_backend:
        # Fallback routing for standard Codex model IDs (e.g. gpt-5.5, gpt-4o) without custom prefixes
        # Load catalog dynamically to classify active models
        catalog_models = []
        if os.path.exists(CATALOG_PATH):
            try:
                with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                    catalog_models = catalog.get("models", [])
            except Exception:
                pass

        if not catalog_models:
            if ENABLE_DEEPSEEK:
                for model in DEEPSEEK_MODELS:
                    catalog_models.append({"id": f"deepseek/{model}"})
            for b in LOCAL_BACKENDS:
                catalog_models.append({"id": f"{b['name']}/local-default"})

        if catalog_models:
            # Codex UI hardcodes standard models when wire_api="responses".
            # We map GPT-5.4 and lower to Flash (low-tier), and GPT-5.5 to Pro (high-tier).
            is_flash_request = any(keyword in model_id.lower() for keyword in ["mini", "flash", "lite", "5.4", "5.3", "5.2"])
            
            flash_keywords = ["mini", "flash", "lite", "fast", "coder", "qwen"]
            flash_models = [m for m in catalog_models if any(kw in m["id"].lower() for kw in flash_keywords)]
            pro_models = [m for m in catalog_models if m not in flash_models]
            
            selected_model_id = ""
            if is_flash_request:
                if flash_models:
                    selected_model_id = flash_models[0]["id"]
                elif catalog_models:
                    selected_model_id = catalog_models[0]["id"]
            else:
                if pro_models:
                    selected_model_id = pro_models[0]["id"]
                elif catalog_models:
                    selected_model_id = catalog_models[0]["id"]
            
            # Resolve target backend and model from selected_model_id
            if selected_model_id:
                if selected_model_id.startswith("deepseek/"):
                    target_backend = {
                        "name": "deepseek",
                        "url": "https://api.deepseek.com/v1"
                    }
                    target_model = selected_model_id.replace("deepseek/", "")
                else:
                    for b in LOCAL_BACKENDS:
                        prefix = f"{b['name']}/"
                        if selected_model_id.startswith(prefix):
                            target_backend = b
                            target_model = selected_model_id.replace(prefix, "")
                            break
                            
            if target_backend:
                print(f"[router] Routing standard model '{model_id}' to dynamic fallback: '{selected_model_id}'")
        
        if not target_backend:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported model provider routing for model ID: {model_id}"
            )

    # 1. Transform Codex layout to standard chat completions request
    transformed_payload = transform_request(codex_payload, target_model)

    stream_mode = transformed_payload.get('stream', False)

    # Record to in-memory stats for the dashboard
    record_request(
        client_model=model_id,
        target_backend=target_backend['name'],
        target_model=target_model,
        stream=stream_mode,
    )

    print("----------------------------------------------------------------------")
    print(f"🎯 [PROXY SUCCESS] Incoming request processed!")
    print(f"   📥 Client Selection: {model_id}")
    print(f"   🔀 Routed Backend:   {target_backend['name'].upper()} ({target_backend['url']})")
    print(f"   📤 Target Model:     {target_model}")
    print(f"   🔄 Stream Mode:      {stream_mode}")
    print("----------------------------------------------------------------------")

    # 2. Build headers
    headers = {"Content-Type": "application/json"}
    if target_backend["name"] == "deepseek":
        if not DEEPSEEK_KEY:
            raise HTTPException(status_code=401, detail="DEEPSEEK_API_KEY is not configured in gateway.env.")
        headers["Authorization"] = f"Bearer {DEEPSEEK_KEY}"

    # 3. Stream Response Mode
    if transformed_payload.get("stream", False):
        async def stream_generator():
            import time
            resp_id = "resp_" + str(int(time.time()))
            full_text = ""
            
            # A. Emit event: response.created
            event_created = {
                "type": "response.created",
                "response": {
                    "id": resp_id,
                    "status": "in_progress",
                    "model": model_id
                }
            }
            yield f"event: response.created\ndata: {json.dumps(event_created)}\n\n"

            # A2. Emit event: response.output_item.added
            event_item_added = {
                "type": "response.output_item.added",
                "response_id": resp_id,
                "output_index": 0,
                "item": {
                    "id": "item_123",
                    "type": "message",
                    "status": "in_progress",
                    "role": "assistant",
                    "content": []
                }
            }
            yield f"event: response.output_item.added\ndata: {json.dumps(event_item_added)}\n\n"

            try:
                async with client.stream(
                    "POST",
                    f"{target_backend['url']}/chat/completions",
                    json=transformed_payload,
                    headers=headers
                ) as r:
                    if r.status_code != 200:
                        event_error = {
                            "type": "response.error",
                            "error": {"message": f"Upstream error: Status {r.status_code}"}
                        }
                        yield f"event: response.error\ndata: {json.dumps(event_error)}\n\n"
                        return

                    # Instantiate R1 think tags filter
                    # Discard think blocks in code completion to prevent agent parsing bugs
                    discard_think = "reasoner" not in target_model and "pro" not in target_model
                    think_filter = ThinkStreamFilter(discard_think=discard_think)
                    in_reasoning = False

                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            line_content = line[6:]
                            if line_content.strip() == "[DONE]":
                                continue
                            try:
                                openai_chunk = json.loads(line_content)
                                for choice in openai_chunk.get("choices", []):
                                    delta = choice.get("delta", {})
                                    
                                    # 1. Capture DeepSeek R1 reasoning stream tracing
                                    reasoning_text = delta.get("reasoning_content", "")
                                    raw_text = delta.get("content", "")
                                    
                                    process_text = ""
                                    if reasoning_text:
                                        if not in_reasoning:
                                            process_text += "<think>"
                                            in_reasoning = True
                                        process_text += reasoning_text
                                    else:
                                        if in_reasoning:
                                            process_text += "</think>"
                                            in_reasoning = False
                                        if raw_text:
                                            process_text += raw_text

                                    if process_text:
                                        filtered_text = think_filter.process(process_text)
                                        if filtered_text:
                                            full_text += filtered_text
                                            # B. Emit event: response.output_text.delta
                                            event_delta = {
                                                "type": "response.output_text.delta",
                                                "item_id": "item_123",
                                                "delta": filtered_text,
                                                "output_index": 0
                                            }
                                            yield f"event: response.output_text.delta\ndata: {json.dumps(event_delta)}\n\n"
                            except Exception:
                                pass

                    # Ensure any open reasoning tags are safely closed if stream ends abruptly
                    if in_reasoning:
                        filtered_text = think_filter.process("</think>")
                        if filtered_text:
                            full_text += filtered_text
                            event_delta = {
                                "type": "response.output_text.delta",
                                "item_id": "item_123",
                                "delta": filtered_text,
                                "output_index": 0
                            }
                            yield f"event: response.output_text.delta\ndata: {json.dumps(event_delta)}\n\n"
            except Exception as e:
                event_error = {
                    "type": "response.error",
                    "error": {"message": f"Proxy stream error: {str(e)}"}
                }
                yield f"event: response.error\ndata: {json.dumps(event_error)}\n\n"

            # C. Emit event: response.output_text.done
            event_text_done = {
                "type": "response.output_text.done",
                "item_id": "item_123",
                "output_index": 0
            }
            yield f"event: response.output_text.done\ndata: {json.dumps(event_text_done)}\n\n"

            # C2. Emit event: response.output_item.done
            event_item_done = {
                "type": "response.output_item.done",
                "response_id": resp_id,
                "output_index": 0,
                "item": {
                    "id": "item_123",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": full_text
                        }
                    ]
                }
            }
            yield f"event: response.output_item.done\ndata: {json.dumps(event_item_done)}\n\n"

            # D. Emit event: response.completed
            event_completed = {
                "type": "response.completed",
                "response": {
                    "id": resp_id,
                    "status": "completed",
                    "model": model_id,
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 100,
                        "total_tokens": 200,
                        "prompt_tokens": 100,
                        "completion_tokens": 100
                    }
                }
            }
            yield f"event: response.completed\ndata: {json.dumps(event_completed)}\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    # 4. Standard Blocking Response Mode
    else:
        try:
            res = await client.post(
                f"{target_backend['url']}/chat/completions",
                json=transformed_payload,
                headers=headers
            )
            if res.status_code != 200:
                raise HTTPException(
                    status_code=res.status_code,
                    detail=f"Upstream returned HTTP error: {res.text}"
                )
            
            openai_res = res.json()
            codex_res = transform_full_response(openai_res, model_id)
            return codex_res
        except HTTPException as he:
            raise he
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Proxy internal connection error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # Start proxy server locally reading port from environment variable
    port_env = os.getenv("GATEWAY_PORT", "8000")
    try:
        port = int(port_env)
    except ValueError:
        port = 8000
    uvicorn.run(app, host="127.0.0.1", port=port)
