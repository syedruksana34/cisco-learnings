import os
import json
import uuid

import httpx
from fastapi import HTTPException
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1/"


def provider():
    name = os.getenv("AI_PROVIDER", "openai").strip().lower()
    if name not in ("openai", "gemini", "ollama"):
        raise HTTPException(503, "AI_PROVIDER must be openai, gemini or ollama")
    return name


def client():
    name = provider()
    if name == "ollama":
        return OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL, timeout=180, max_retries=0,
                      http_client=httpx.Client(trust_env=False))
    key_name = "GEMINI_API_KEY" if name == "gemini" else "OPENAI_API_KEY"
    key = os.getenv(key_name, "").strip()
    if not key:
        raise HTTPException(503, f"{key_name} is not configured")
    kwargs = {"api_key": key, "timeout": 30, "max_retries": 0}
    if name == "gemini":
        kwargs["base_url"] = GEMINI_BASE_URL
    return OpenAI(**kwargs)


def chat_model():
    if provider() == "ollama":
        return os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    if provider() == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def fallback_model():
    if provider() == "gemini":
        return os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash").strip()
    return ""


def embedding_model():
    if provider() == "ollama":
        return os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    if provider() == "gemini":
        return os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    return os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def ollama_chat(model: str, messages: list, tools: list):
    names = {}
    native_messages = []
    for message in messages:
        converted = dict(message)
        if converted.get("tool_calls"):
            converted["tool_calls"] = []
            for call in message["tool_calls"]:
                names[call["id"]] = call["function"]["name"]
                converted["tool_calls"].append({"function": {
                    "name": call["function"]["name"],
                    "arguments": json.loads(call["function"]["arguments"]),
                }})
        if converted["role"] == "tool":
            call_id = converted.pop("tool_call_id")
            converted["tool_name"] = names[call_id]
        native_messages.append(converted)
    try:
        response = httpx.post("http://127.0.0.1:11434/api/chat",
                              json={"model": model, "messages": native_messages, "tools": tools,
                                    "stream": False, "think": False},
                              timeout=180, trust_env=False)
    except httpx.RequestError as exc:
        raise HTTPException(503, "Local Ollama is unavailable or timed out") from exc
    if not response.is_success:
        raise HTTPException(503, f"Local Ollama returned HTTP {response.status_code}. Check the model and service.")
    try:
        message = response.json()["message"]
        calls = [{"id": str(uuid.uuid4()), "type": "function", "function": {
            "name": call["function"]["name"], "arguments": json.dumps(call["function"]["arguments"])}}
                 for call in message.get("tool_calls", [])]
        return ChatCompletionMessage.model_validate(
            {"role": "assistant", "content": message.get("content") or None, "tool_calls": calls or None})
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "Local Ollama returned an invalid response") from exc
