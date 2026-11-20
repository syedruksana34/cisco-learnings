from asyncio import Lock
from contextlib import asynccontextmanager, closing
from pathlib import Path
import re
import sqlite3
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
import httpx
from pydantic import BaseModel

ADD_STUDENT = re.compile(r"(?:add|create)\s+(?:a\s+)?student[.!?]?", re.IGNORECASE)

def connect():
    db = sqlite3.connect(Path(__file__).with_name("college.sqlite3"))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


@asynccontextmanager
async def lifespan(app):
    with closing(connect()) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS departments (department_id INTEGER PRIMARY KEY, department_name TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS students (student_id INTEGER PRIMARY KEY, student_name TEXT NOT NULL, department_id INTEGER NOT NULL REFERENCES departments(department_id))")
    app.state.chat_sessions = {}
    yield

app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: UUID
    message: str | None = None
    confirmation_id: UUID | None = None
    approved: bool | None = None


def visible_reply(output: object) -> str:
    text = str(output)
    closing_tag = re.split(r"</think\s*>", text, flags=re.IGNORECASE)
    answer = re.split(r"<think\b[^>]*>", closing_tag[-1], maxsplit=1, flags=re.IGNORECASE)[0].strip()
    return answer or "No final reply was returned. Check the directory before retrying a change."


async def guide_student_creation(client: httpx.AsyncClient, api_url: str, message: str, draft: dict) -> str:
    if message.casefold() == "cancel":
        draft.clear()
        return "Student creation cancelled."

    response = await client.get(f"{api_url}/departments/")
    response.raise_for_status()
    departments = {row["department_id"]: row["department_name"] for row in response.json()}
    if not departments:
        draft.clear()
        return "Create a department before adding a student."

    choices = ", ".join(f"{record_id}: {name}" for record_id, name in departments.items())
    dept = re.fullmatch(r"department\s+(\d+)[.!?]?", message, re.IGNORECASE)
    if ADD_STUDENT.fullmatch(message):
        draft.clear()
        draft["active"] = True
        return f"What's the student's full name? You can also send the department first (e.g. 'department {next(iter(departments))}'). Available: {choices}."
    if dept or ("name" in draft and message.isdecimal()):
        department_id = int(dept[1] if dept else message)
        if department_id not in departments:
            return f"That department doesn't exist. Choose from: {choices}."
        draft["department_id"] = department_id
    elif "name" not in draft:
        if not re.fullmatch(r"[^\W\d_]+(?:[ .'-]+[^\W\d_]+)*\.?", message):
            return "Enter the student's name, or type 'cancel'."
        draft["name"] = message
    else:
        return f"Enter the department ID or type 'cancel'. Available: {choices}."

    if "name" not in draft:
        return f"Department: {departments[draft['department_id']]}. What's the student's full name?"
    if draft.get("department_id") not in departments:
        draft.pop("department_id", None)
        return f"Which department should {draft['name']} join? Available: {choices}."

    response = await client.post(f"{api_url}/students/", json={
        "student_name": draft["name"], "department_id": draft["department_id"],
    })
    response.raise_for_status()
    student = response.json()
    draft.clear()
    department_name = departments[student["department_id"]]
    return f"Added {student['student_name']} to {department_name}.\nStudent ID: {student['student_id']}"


COMMAND = re.compile(
    r"(?:(?:can|could|would) you\s+)?(?:please\s+)?"
    r"(list|show|find|get|read|add|create|rename|edit|update|move|delete|remove)\s+"
    r"(?:all\s+|al\s+|the\s+|an?\s+)?(students?|departments?)(?:\s+(.+))?",
    re.IGNORECASE,
)


async def college_command(client: httpx.AsyncClient, api_url: str, message: str, pending: dict) -> str | None:
    command = COMMAND.fullmatch(message.rstrip(".?!"))
    if not command:
        return None
    action, entity = command[1].lower(), command[2].lower().rstrip("s")
    subject = command[3] or ""
    url = f"{api_url}/{entity}s/"
    name_key, id_key = f"{entity}_name", f"{entity}_id"

    async def resolve(collection: str, target: str) -> dict:
        target = re.sub(r"^(?:with (?:id|name)|id|named)\s*[:=]?\s+", "", target, flags=re.IGNORECASE).strip(" \"'")
        identifier = re.fullmatch(r"#?(\d+)", target)
        response = await client.get(f"{api_url}/{collection}s/" + (identifier[1] if identifier else ""))
        if identifier and response.status_code == 404:
            raise HTTPException(404, f"No {collection} found with ID {identifier[1]}.")
        response.raise_for_status()
        if identifier:
            return response.json()
        matches = [row for row in response.json() if row[f"{collection}_name"].casefold() == target.casefold()]
        if len(matches) > 1:
            ids = ", ".join(str(row[f"{collection}_id"]) for row in matches)
            raise HTTPException(409, f"More than one {collection} matches. Specify one ID: {ids}.")
        if not matches:
            raise HTTPException(404, f"No {collection} named {target} was found. Check the name or use its ID.")
        return matches[0]

    try:
        if action in {"list", "show", "find", "get", "read"}:
            if not subject:
                response = await client.get(url)
                response.raise_for_status()
                rows = response.json()
            else:
                rows = [await resolve(entity, subject)]
            return "\n\n".join(f"{row[name_key]}\n{entity.title()} ID: {row[id_key]}" for row in rows) or f"No {entity}s found."

        if not subject:
            if action in {"add", "create"} and entity == "student":
                return None
            if action in {"add", "create"}:
                return "What department should I add? Send its name after 'Add department'."
            return f"Which {entity} should I {action}? Include its name or ID."

        if action in {"add", "create"}:
            name = re.sub(r"^named\s+", "", subject, flags=re.IGNORECASE)
            payload = {name_key: name.strip(" \"'")}
            if entity == "student":
                parts = re.fullmatch(r"(.+?)\s+(?:in|to)\s+(?:the\s+)?(?:department\s+)?(.+)", name, re.IGNORECASE)
                if not parts:
                    return "Include the student's department, for example: Add student Alex Lee to Computer Science."
                department = await resolve("department", parts[2])
                payload = {name_key: parts[1].strip(" \"'"), "department_id": department["department_id"]}
            response = await client.post(url, json=payload)
            verb = "Added"
        elif action in {"delete", "remove"}:
            record = await resolve(entity, subject)
            pending.update(id=uuid4(), url=f"{url}{record[id_key]}", prompt=f"Delete {record[name_key]}?\n{entity.title()} ID: {record[id_key]}")
            return None
        else:
            change = re.fullmatch(r"(.+?)\s+to\s+(.+)", subject, re.IGNORECASE)
            if not change:
                return f"Include the {entity} name or ID and the new value, for example: Rename {entity} ID 1 to New Name."
            record = await resolve(entity, change[1])
            value = change[2]
            payload = {name_key: value.strip(" \"'")}
            if entity == "student":
                payload["department_id"] = record["department_id"]
                if action == "move":
                    target = re.sub(r"^(?:the\s+)?department\s+", "", value, flags=re.IGNORECASE)
                    department = await resolve("department", target)
                    payload = {name_key: record[name_key], "department_id": department["department_id"]}
            elif action == "move":
                return "Only students can move to another department."
            response = await client.put(f"{url}{record[id_key]}", json=payload)
            verb = "Updated"
        if response.is_error:
            return response.json().get("detail", "The college API rejected that change.")
        saved = response.json()
        return f"{verb} {saved[name_key]}.\n{entity.title()} ID: {saved[id_key]}"
    except HTTPException as exc:
        if exc.status_code not in {404, 409}:
            raise
        return str(exc.detail)


@app.post("/chat")
async def chat(payload: ChatRequest, request: Request):
    from agents import Runner, SQLiteSession
    from openai import APIConnectionError, NotFoundError
    from .main import API_URL, LOCAL_MODEL, LOCAL_RUN_CONFIG, ChatContext, agent

    sessions = request.app.state.chat_sessions
    session_id = str(payload.session_id)
    if session_id not in sessions:
        sessions[session_id] = (Lock(), SQLiteSession(session_id), {}, {})
    lock, history, pending, student_draft = sessions[session_id]

    async with lock:
        if payload.confirmation_id is not None:
            if payload.approved is None or payload.confirmation_id != pending.get("id"):
                raise HTTPException(409, "No matching deletion is awaiting confirmation.")
            url = pending["url"]
            pending.clear()
            if payload.approved:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=request.app)) as client:
                    response = await client.delete(url)
                reply = "Deleted." if response.status_code == 204 else response.json().get("detail", "Could not delete the record.")
            else:
                reply = "Deletion cancelled."
            await history.add_items([{"role": "assistant", "content": reply}])
            return {"reply": reply}

        if not payload.message or not payload.message.strip() or payload.approved is not None:
            raise HTTPException(422, "Send a message or respond to a pending confirmation.")
        if not pending:
            message = payload.message.strip()
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=request.app)) as client:
                    reply = await college_command(client, API_URL, message, pending)
                    if reply is None and not pending and (student_draft or ADD_STUDENT.fullmatch(message)):
                        reply = await guide_student_creation(client, API_URL, message, student_draft)
            except httpx.HTTPError as exc:
                raise HTTPException(503, "Could not complete the request. Check the directory before retrying.") from exc
            if pending:
                return {"confirmation": {"id": pending["id"], "prompt": pending["prompt"]}}
            if reply is not None:
                await history.add_items([
                    {"role": "user", "content": message}, {"role": "assistant", "content": reply},
                ])
                return {"reply": reply}
            context = ChatContext(browser=True)
            try:
                result = await Runner.run(
                    agent, payload.message.strip(), session=history, context=context,
                    run_config=LOCAL_RUN_CONFIG,
                )
            except APIConnectionError as exc:
                raise HTTPException(503, "Cannot reach local Ollama. Start it with `ollama serve`.") from exc
            except NotFoundError as exc:
                raise HTTPException(503, f"The local model is unavailable. Run `ollama pull {LOCAL_MODEL}`.") from exc
            if context.pending_delete is None:
                return {"reply": visible_reply(result.final_output)}
            url, prompt = context.pending_delete
            pending.update(id=uuid4(), url=url, prompt=prompt)
        return {"confirmation": {"id": pending["id"], "prompt": pending["prompt"]}}


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/api/{resource}/")
@app.post("/api/{resource}/", status_code=201)
@app.get("/api/{resource}/{record_id}")
@app.put("/api/{resource}/{record_id}")
@app.delete("/api/{resource}/{record_id}", status_code=204)
def crud(resource: Literal["students", "departments"], request: Request,
         record_id: int | None = None, payload: dict | None = None):
    id_key, name_key = ("student_id", "student_name") if resource == "students" else ("department_id", "department_name")
    with closing(connect()) as db, db:
        if request.method == "GET" and record_id is None:
            return [dict(row) for row in db.execute(f"SELECT * FROM {resource} ORDER BY {id_key}")]
        query = f"SELECT * FROM {resource} WHERE {id_key} = ?"
        if record_id is not None:
            row = db.execute(query, (record_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Record not found")
            if request.method == "GET":
                return dict(row)
        try:
            if request.method == "DELETE":
                db.execute(f"DELETE FROM {resource} WHERE {id_key} = ?", (record_id,))
                return Response(status_code=204)

            data = payload or {}
            name = data.get(name_key)
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(422, f"{name_key} is required")
            columns, values = (name_key,), (name.strip(),)
            if resource == "students":
                department_id = data.get("department_id")
                if type(department_id) is not int:
                    raise HTTPException(422, "department_id must be an integer")
                columns += ("department_id",)
                values += (department_id,)
            if request.method == "POST":
                placeholders = ", ".join("?" for _ in columns)
                record_id = db.execute(f"INSERT INTO {resource} ({', '.join(columns)}) VALUES ({placeholders})", values).lastrowid
            else:
                assignments = ", ".join(f"{column} = ?" for column in columns)
                db.execute(f"UPDATE {resource} SET {assignments} WHERE {id_key} = ?", (*values, record_id))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Check that the department exists and has no students before deleting it.") from exc
        return dict(db.execute(query, (record_id,)).fetchone())