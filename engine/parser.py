def transform_request(codex_payload: dict, actual_model: str) -> dict:
    """
    Transforms Codex Responses request parameters into standard OpenAI Chat Completions payload structure.
    """
    prompt = codex_payload.get("prompt", "")
    
    # Pack prompt into user role message
    messages = [{"role": "user", "content": prompt}]
    
    # Prepend optional system instructions if provided
    if "system" in codex_payload and codex_payload["system"]:
        messages.insert(0, {"role": "system", "content": codex_payload["system"]})

    # Assemble request payload compliant with standard OpenAI schemas
    transformed = {
        "model": actual_model,
        "messages": messages,
        "temperature": codex_payload.get("temperature", 0.2),
        "max_tokens": codex_payload.get("max_tokens", 1024),
        "top_p": codex_payload.get("top_p", 1.0),
        "stream": codex_payload.get("stream", False)
    }

    # Pass through standard hyperparameters if explicitly passed
    for param in ["presence_penalty", "frequency_penalty", "stop"]:
        if param in codex_payload:
            transformed[param] = codex_payload[param]

    return transformed

def transform_response_chunk(openai_chunk: dict, original_model_id: str) -> dict:
    """
    Translates a standard OpenAI stream chunk into Codex Responses stream chunk format.
    """
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
    """
    Translates a standard OpenAI non-streaming response into Codex Responses format.
    """
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
