import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import errors, types
import httpx
from pydantic import BaseModel, Field, field_validator, model_validator


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
logger = logging.getLogger(__name__)
app = FastAPI(title="Gemini Chat")
app.mount(
    "/ai-assets",
    StaticFiles(directory=BASE_DIR / "ai_frontend"),
    name="ai-assets",
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def trim_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message content cannot be blank.")
        return value


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_conversation(self) -> "ChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("The latest message must be from the user.")
        if sum(len(message.content) for message in self.messages) > 20000:
            raise ValueError("Conversation content must not exceed 20,000 characters.")
        return self


@app.get("/", include_in_schema=False)
def chat_page():
    return FileResponse(BASE_DIR / "ai_frontend" / "index.html")


@app.post("/api/chat")
async def chat(request: ChatRequest):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Gemini is not configured. Set GEMINI_API_KEY in python_with_ai/.env and restart the server.",
        )

    contents = [
        types.Content(
            role="user" if message.role == "user" else "model",
            parts=[types.Part.from_text(text=message.content)],
        )
        for message in request.messages
    ]

    try:
        async with genai.Client(api_key=api_key).aio as client:
            response = await client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
                contents=contents,
            )
    except errors.APIError as exc:
        logger.warning("Gemini API request failed with status %s", exc.code)
        if exc.code in (400, 401, 403):
            raise HTTPException(
                status_code=502,
                detail=(
                    "Gemini rejected the request. Check the API key, model, and "
                    "Google AI Studio project settings."
                ),
            ) from exc
        if exc.code == 429:
            raise HTTPException(
                status_code=429,
                detail="Gemini quota or rate limit reached. Check your Google AI Studio usage and billing.",
            ) from exc
        if exc.code == 404:
            raise HTTPException(
                status_code=502,
                detail=(
                    "The configured Gemini model is unavailable for this API key. "
                    "Check GEMINI_MODEL in python_with_ai/.env or select a model "
                    "available to your Google AI Studio project."
                ),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Gemini could not complete the request. Check the server logs.",
        ) from exc
    except (httpx.RequestError, OSError, RuntimeError, TimeoutError) as exc:
        logger.exception("Gemini connection failed")
        raise HTTPException(
            status_code=502,
            detail="Could not connect to Gemini. Check the server logs.",
        ) from exc

    if not response.text:
        logger.warning("Gemini returned no text for the chat request")
        raise HTTPException(
            status_code=502,
            detail="Gemini returned no text. The response may have been blocked or incomplete.",
        )

    return {"reply": response.text}