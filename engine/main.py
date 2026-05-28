import os
import sys
import json
import httpx
import asyncio

# Add parent directory to sys.path to enable absolute imports of engine modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from engine.parser import transform_request, transform_response_chunk, transform_full_response
from engine.think_handler import ThinkStreamFilter

# Load configurations from gateway.env
load_dotenv("gateway.env")

app = FastAPI(title="Codex Hybrid API Gateway")

# Global HTTP async client
client = httpx.AsyncClient(timeout=60.0)

# 1. Read Cloud DeepSeek settings
ENABLE_DEEPSEEK = os.getenv("ENABLE_DEEPSEEK", "true").lower() == "true"
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODELS_RAW = os.getenv("DEEPSEEK_MODELS", "deepseek-coder,deepseek-reasoner,deepseek-chat")
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
    os.makedirs("config", exist_ok=True)
    with open("config/model-catalog.json", "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)
    
    print(f"[catalog] Completed. Unified catalog contains {len(catalog['models'])} models.")

@app.post("/v1/responses")
async def handle_responses(request: Request):
    """
    Main proxy endpoint intercepting Codex Responses API calls.
    Performs prefix-based model routing, translates requests, and returns
    SSE streaming or full JSON payloads back.
    """
    try:
        codex_payload = await request.json()
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
        if ENABLE_DEEPSEEK and DEEPSEEK_MODELS:
            fallback_model = "deepseek-v4-pro" if "deepseek-v4-pro" in DEEPSEEK_MODELS else DEEPSEEK_MODELS[0]
            target_backend = {
                "name": "deepseek",
                "url": "https://api.deepseek.com/v1"
            }
            target_model = fallback_model
            print(f"[router] Routing standard model '{model_id}' to DeepSeek fallback: '{target_model}'")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported model provider routing for model ID: {model_id}"
            )

    # 1. Transform Codex layout to standard chat completions request
    transformed_payload = transform_request(codex_payload, target_model)

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

                    async for line in r.iter_lines():
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
                                    raw_text = delta.get("content", "")
                                    if raw_text:
                                        filtered_text = think_filter.process(raw_text)
                                        if filtered_text:
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

            # D. Emit event: response.completed
            event_completed = {
                "type": "response.completed",
                "response": {
                    "id": resp_id,
                    "status": "completed",
                    "model": model_id,
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 100,
                        "total_tokens": 200
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
