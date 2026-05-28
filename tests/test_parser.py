import os
import sys

# Ensure engine is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.parser import transform_request, transform_response_chunk, transform_full_response

def test_request_payload_transformation():
    """
    Tests transforming a proprietary Codex prompt payload to a standard OpenAI chat request.
    """
    codex_payload = {
        "model": "deepseek/deepseek-v4-flash",
        "prompt": "import math\ndef is_prime(n):",
        "temperature": 0.1,
        "max_tokens": 150,
        "stream": True,
        "system": "You are a helpful software engineer assistant."
    }
    
    openai_req = transform_request(codex_payload, "deepseek-v4-flash")
    
    assert openai_req["model"] == "deepseek-v4-flash"
    assert openai_req["temperature"] == 0.1
    assert openai_req["max_tokens"] == 150
    assert openai_req["stream"] is True
    assert len(openai_req["messages"]) == 2
    assert openai_req["messages"][0]["role"] == "system"
    assert openai_req["messages"][0]["content"] == "You are a helpful software engineer assistant."
    assert openai_req["messages"][1]["role"] == "user"
    assert openai_req["messages"][1]["content"] == "import math\ndef is_prime(n):"

def test_chunk_response_transformation():
    """
    Tests translating an OpenAI streaming chunk to Codex Responses format.
    """
    openai_chunk = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 1677649420,
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "delta": {"content": "\n    if n <= 1: return False"},
                "finish_reason": None
            }
        ]
    }
    
    codex_chunk = transform_response_chunk(openai_chunk, "deepseek/deepseek-v4-flash")
    
    assert codex_chunk["id"] == "chatcmpl-123"
    assert codex_chunk["model"] == "deepseek/deepseek-v4-flash"
    assert codex_chunk["object"] == "text_completion.chunk"
    assert len(codex_chunk["choices"]) == 1
    assert codex_chunk["choices"][0]["text"] == "\n    if n <= 1: return False"
    assert codex_chunk["choices"][0]["index"] == 0
    assert codex_chunk["choices"][0]["finish_reason"] is None

def test_full_response_transformation():
    """
    Tests translating a standard non-streaming response to stateful Codex Responses format.
    """
    openai_res = {
        "id": "chatcmpl-456",
        "object": "chat.completion",
        "created": 1677649430,
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Done!"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17
        }
    }
    
    codex_res = transform_full_response(openai_res, "deepseek/deepseek-v4-flash")
    
    assert codex_res["id"] == "resp_chatcmpl-456"
    assert codex_res["model"] == "deepseek/deepseek-v4-flash"
    assert codex_res["object"] == "response"
    assert codex_res["status"] == "completed"
    assert codex_res["output"][0]["content"][0]["text"] == "Done!"
    assert codex_res["usage"]["input_tokens"] == 12
    assert codex_res["usage"]["output_tokens"] == 5
    assert codex_res["usage"]["total_tokens"] == 17

def test_request_input_array_transformation():
    """
    Tests transforming a stateful input array containing developer and user messages into Chat messages.
    """
    codex_payload = {
        "model": "deepseek/deepseek-v4-flash",
        "input": [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": "System guidance"}]
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello world"}]
            }
        ],
        "temperature": 0.3,
        "max_tokens": 200,
        "stream": False
    }
    
    openai_req = transform_request(codex_payload, "deepseek-v4-flash")
    
    assert openai_req["model"] == "deepseek-v4-flash"
    assert openai_req["temperature"] == 0.3
    assert openai_req["max_tokens"] == 200
    assert len(openai_req["messages"]) == 2
    assert openai_req["messages"][0]["role"] == "system"
    assert openai_req["messages"][0]["content"] == "System guidance"
    assert openai_req["messages"][1]["role"] == "user"
    assert openai_req["messages"][1]["content"] == "Hello world"
