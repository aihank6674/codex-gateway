def transform_request(codex_payload: dict, actual_model: str) -> dict:
    """
    Transforms Codex Responses request parameters into standard OpenAI Chat Completions payload structure.
    """
    messages = []
    
    # 1. Map stateful "input" message array if provided (Chat Mode)
    if "input" in codex_payload and isinstance(codex_payload["input"], list):
        for msg in codex_payload["input"]:
            role = msg.get("role", "user")
            # Map developer role to standard system role
            if role == "developer":
                role = "system"
                
            raw_content = msg.get("content", "")
            content_str = ""
            
            if isinstance(raw_content, list):
                for part in raw_content:
                    if isinstance(part, dict):
                        if part.get("type") == "input_text":
                            content_str += part.get("text", "")
                        elif "text" in part:
                            content_str += part["text"]
            else:
                content_str = str(raw_content)
                
            messages.append({"role": role, "content": content_str})
            
    # 2. Fallback to "prompt" parameter (Autocomplete / Inline Completion Mode)
    else:
        prompt = codex_payload.get("prompt", "")
        messages = [{"role": "user", "content": prompt}]
        
        # Prepend system prompt if provided
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
    for param in ["presence_penalty", "frequency_penalty", "stop", "reasoning_effort"]:
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
    Translates a standard OpenAI non-streaming response into stateful Codex Responses format.
    """
    choices = openai_res.get("choices", [])
    text = ""
    if choices:
        msg = choices[0].get("message", {})
        text = msg.get("content", "")

    usage = openai_res.get("usage", {}) or {}
    
    return {
        "id": "resp_" + openai_res.get("id", "chatcmpl-local"),
        "object": "response",
        "status": "completed",
        "model": original_model_id,
        "output": [
            {
                "id": "item_123",
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text
                    }
                ]
            }
        ],
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 100),
            "output_tokens": usage.get("completion_tokens", 100),
            "total_tokens": usage.get("total_tokens", 200),
            "prompt_tokens": usage.get("prompt_tokens", 100),
            "completion_tokens": usage.get("completion_tokens", 100)
        }
    }
