import asyncio
from dataclasses import dataclass
import os
from typing import Literal

import httpx
from agents import (
    Agent, ModelSettings, OpenAIChatCompletionsModel, RunConfig, RunContextWrapper, Runner,
    SQLiteSession, function_tool,
)
from openai import AsyncOpenAI

API_URL = "http://127.0.0.1:8000/api"
LOCAL_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
LOCAL_RUN_CONFIG = RunConfig(tracing_disabled=True)


@dataclass
class ChatContext:
    browser: bool = False
    pending_delete: tuple[str, str] | None = None


async def delete_record(url: str) -> str:
    async with httpx.AsyncClient(timeout=5) as client:
        result = await client.delete(url)
    return "Deleted." if result.status_code == 204 else f"HTTP {result.status_code}: {result.text}"


@function_tool
async def college_crud(ctx: RunContextWrapper[ChatContext],
                 resource: Literal["students", "departments"],
                 action: Literal["list", "read", "create", "update", "delete"],
                 record_id: int | None = None, name: str | None = None,
                 department_id: int | None = None) -> str:
    """Manage college records. Read, update, and delete require a record ID."""
    url = f"{API_URL}/{resource}/"
    if action in ("read", "update", "delete"):
        if record_id is None:
            return "A record ID is required."
        url += str(record_id)

    payload = None
    if action in ("create", "update"):
        if not name or (resource == "students" and department_id is None):
            return "A name is required. Students also need a department ID."
        if resource == "students":
            payload = {"student_name": name, "department_id": department_id}
        else:
            payload = {"department_name": name}

    if action == "delete":
        async with httpx.AsyncClient(timeout=5) as client:
            record = await client.get(url)
        if not record.is_success:
            return f"HTTP {record.status_code}: {record.text}"
        prompt = f"Delete this record? {record.json()}"
        if ctx.context.browser:
            if ctx.context.pending_delete is None:
                ctx.context.pending_delete = (url, prompt)
            return "No record was deleted. Waiting for browser confirmation."
        answer = await asyncio.to_thread(input, f"{prompt} Type yes: ")
        if answer.strip().lower() != "yes":
            return "Deletion cancelled."
        return await delete_record(url)

    methods = {"list": "GET", "read": "GET", "create": "POST", "update": "PUT"}
    async with httpx.AsyncClient(timeout=5) as client:
        result = await client.request(methods[action], url, json=payload)
    return f"HTTP {result.status_code}: {result.text}"


agent = Agent(
    name="College Assistant",
    model=OpenAIChatCompletionsModel(
        model=LOCAL_MODEL,
        openai_client=AsyncOpenAI(
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama",
            http_client=httpx.AsyncClient(trust_env=False),
            max_retries=0,
        ),
    ),
    model_settings=ModelSettings(extra_body={"reasoning_effort": "none"}),
    tools=[college_crud],
    instructions="Use the college_crud tool for every request about college records. "
    "Look up names to find IDs. Ask if multiple records match. "
    "Before an update, read the record and preserve unchanged fields. "
    "Only request one deletion at a time. Stop and wait when browser confirmation is pending. "
    "Report API errors and do not claim a write succeeded unless it did.",
)

if __name__ == "__main__":
    session = SQLiteSession("college-demo")
    while (message := input("College> ").strip()) != "exit":
        if message:
            print(Runner.run_sync(
                agent, message, session=session, context=ChatContext(), run_config=LOCAL_RUN_CONFIG,
            ).final_output)