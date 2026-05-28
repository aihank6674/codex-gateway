import os
import json
import httpx
import asyncio
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
            name_suffix = "Reasoner (R1)" if "reasoner" in model else "Coder"
            if model == "deepseek-chat":
                name_suffix = "General Chat (V3)"
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
            try:
                async with client.stream(
                    "POST",
                    f"{target_backend['url']}/chat/completions",
                    json=transformed_payload,
                    headers=headers
                ) as r:
                    if r.status_code != 200:
                        yield f"data: {json.dumps({'error': f'Upstream error: Status {r.status_code}'})}\n\n"
                        return

                    # Instantiate R1 think tags filter
                    # Discard think blocks in code completion to prevent agent parsing bugs
                    discard_think = "reasoner" not in target_model
                    think_filter = ThinkStreamFilter(discard_think=discard_think)

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
                                
                                # Intercept and filter DeepSeek-R1 thinking streams
                                if codex_chunk["choices"] and codex_chunk["choices"][0]["text"]:
                                    raw_text = codex_chunk["choices"][0]["text"]
                                    filtered_text = think_filter.process(raw_text)
                                    codex_chunk["choices"][0]["text"] = filtered_text

                                yield f"data: {json.dumps(codex_chunk)}\n\n"
                            except Exception:
                                pass
            except Exception as e:
                yield f"data: {json.dumps({'error': f'Proxy stream error: {str(e)}'})}\n\n"

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
    # Start proxy server locally on port 8000
    uvicorn.run(app, host="127.0.0.1", port=8000)
