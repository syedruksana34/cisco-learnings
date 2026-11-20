from dataclasses import dataclass
import json
import os
import re

from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, RunConfig, RunContextWrapper, Runner, function_tool
from fastapi import FastAPI, HTTPException
import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, NotFoundError
from pydantic import ValidationError

from .api import EmployeeInput


@dataclass
class EmployeeContext:
    client: httpx.AsyncClient
    result: dict | None = None
    started: bool = False
    create_only: bool = False

    async def request(self, method: str, path: str, **kwargs) -> str:
        if self.started:
            return "Only one operation is allowed per request."
        self.started = True
        response = await self.client.request(method, path, **kwargs)
        data = response.json()
        if response.is_error:
            detail = data.get("detail")
            self.result = {"reply": detail if isinstance(detail, str) else "Check the employee fields and try again."}
        else:
            operation = "read" if method == "GET" else "delete" if path.endswith("/deletion") else "write"
            self.result = {"data": data, "operation": operation}
        return "Operation completed." if not response.is_error else "Operation rejected."


def employee_tool_error(context: RunContextWrapper[EmployeeContext], _error: Exception) -> str:
    if context.context.started:
        return "The operation could not be verified. Check the directory before trying again."
    if context.context.create_only:
        return ADD_DETAILS
    return "I couldn't complete that request. Check the employee ID and details, or use the directory."


@function_tool(failure_error_function=employee_tool_error)
async def find_employees(context: RunContextWrapper[EmployeeContext], search: str = "", employee_id: int | None = None) -> str:
    """List or search employees by name or designation, or read a single employee by ID."""
    return await lookup_employees(context.context, search, employee_id)


async def lookup_employees(context: EmployeeContext, search: str, employee_id: int | None = None) -> str:
    if employee_id is not None:
        return await context.request("GET", f"/api/employees/{employee_id}")
    return await context.request("GET", "/api/employees", params={"search": search})


@function_tool(failure_error_function=employee_tool_error)
async def save_employee(
    context: RunContextWrapper[EmployeeContext], name: str, designation: str, age: int,
    salary: float, employee_id: int | None = None,
) -> str:
    """Create an employee, or replace all fields of the employee with the specified ID."""
    path = "/api/employees"
    employee = {"name": name, "designation": designation, "age": age, "salary": salary}
    if employee_id is not None and not context.context.create_only:
        return await context.context.request("PUT", f"{path}/{employee_id}", json=employee)
    return await context.context.request("POST", path, json=employee)


@function_tool(failure_error_function=employee_tool_error)
async def propose_deletion(context: RunContextWrapper[EmployeeContext], employee_id: int) -> str:
    """Prepare a deletion for the specified employee ID. Does not delete the employee."""
    return await prepare_employee_deletion(context.context, employee_id)


async def prepare_employee_deletion(context: EmployeeContext, employee_id: int) -> str:
    return await context.request("POST", f"/api/employees/{employee_id}/deletion")


MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
MODEL = OpenAIChatCompletionsModel(
    model=MODEL_NAME,
    openai_client=AsyncOpenAI(
        base_url="http://127.0.0.1:11434/v1", api_key="ollama", max_retries=0,
        timeout=30, http_client=httpx.AsyncClient(trust_env=False),
    ),
)


def specialist(name, tool, instructions):
    return Agent(
        name=name, model=MODEL, tools=[tool], tool_use_behavior="stop_on_first_tool",
        model_settings=ModelSettings(max_tokens=384, extra_body={"reasoning_effort": "none"}),
        handoff_description=instructions,
        instructions=instructions + " Keep replies short. Do not invent missing information or expose reasoning.",
    )


AGENTS = {
    "read": specialist("Read Agent", find_employees, "Only list, search or read employees. Use your tool for record requests."),
    "write": specialist("Write Agent", save_employee, "Only create or update an employee. Require explicit name, designation, age and salary. Updates also require ID. Ask for missing fields. Never treat a partial update as a creation."),
    "delete": specialist("Delete Agent", propose_deletion, "Only prepare deletion. Require an explicit employee ID. Never claim that a record was deleted."),
}

SUPERVISOR = Agent(
    name="Supervisor Agent",
    model=MODEL,
    handoffs=list(AGENTS.values()),
    model_settings=ModelSettings(temperature=0, max_tokens=384, extra_body={"reasoning_effort": "none"}),
    instructions=(
        "Route a single employee request by calling the appropriate transfer tool. "
        "Call transfer_to_read_agent to list, find or view; call transfer_to_write_agent to add or update; "
        "call transfer_to_delete_agent to delete or remove. Do not narrate a transfer instead of calling the tool. "
        "If you cannot call a tool, return exactly Read Agent, Write Agent, Delete Agent, or Unclear. "
        "Return Unclear for ambiguous or multiple operations. Do not perform operations or report results yourself."
    ),
)

COMMAND = re.compile(
    r"^(?:(?:could|can|would)\s+you\s+|i\s+(?:want|need)\s+to\s+)?(?:please\s+)?"
    r"(?P<verb>list|show|find|search|view|read|get|add|create|update|edit|delete|remove)\b",
    re.IGNORECASE,
)
ADD_WITHOUT_DETAILS = re.compile(r"(?:add|create)\s+(?:(?:an?|new)\s+|an?\s+new\s+)?employee[.!?]?", re.IGNORECASE)
LIST_EMPLOYEES = re.compile(r"(?:all\s+(?:the\s+)?|the\s+)?(?:employees|employee records)", re.IGNORECASE)
EMPLOYEE_ID = re.compile(r"employee\s+(?:(?:with\s+)?id\s*)?#?(\d+)", re.IGNORECASE)
EMPLOYEE_NAME = re.compile(r"employees?\s+(?:named|with name)\s+(.+)", re.IGNORECASE)
ADD_DETAILS = "What are the employee's full name, designation, age, and salary?"
ADD_FIELDS = re.compile(
    r"(?:name\s+)?(?P<name>[^,\n]+),\s*(?:designation\s+)?(?P<designation>[^,\n]+),\s*"
    r"(?:age\s+)?(?P<age>\d+),\s*(?:salary\s+)?(?P<salary>\d+(?:,\d{3})*(?:\.\d{1,2})?)\.?",
    re.IGNORECASE,
)
ADD_PREFIX = re.compile(r"(?:add|create)\s+(?:an?\s+)?(?:new\s+)?employee\s+(?:with\s+)?", re.IGNORECASE)
FIELD_LABEL = re.compile(r"(?:^|,)\s*(name|designation|desig|age|salary)(?:\s*[:=]\s*|\s+)", re.IGNORECASE)
VERB_TYPOS = {"lsit": "list", "lits": "list", "shwo": "show", "serch": "search", "fnd": "find", "ad": "add", "craete": "create", "updat": "update", "udpate": "update", "delte": "delete", "delet": "delete", "remvoe": "remove"}
SUBJECT_TYPOS = {"employe": "employee", "empoyee": "employee", "emplyee": "employee", "employes": "employees", "empoyees": "employees", "emplyees": "employees"}


def normalize_command(message: str) -> str:
    prefix = re.match(r"^((?:(?:could|can|would)\s+you\s+|i\s+(?:want|need)\s+to\s+)?(?:please\s+)?)([a-z]+)\b", message, re.IGNORECASE)
    if prefix is None:
        return message
    verb = VERB_TYPOS.get(prefix[2].lower(), prefix[2])
    candidate = prefix[1] + verb + message[prefix.end():]
    command = COMMAND.match(candidate)
    if command is None:
        return message
    subject = re.match(r"(\s+(?:(?:al|all|the|an?|new)\s+)*)([a-z]+)\b", candidate[command.end():], re.IGNORECASE)
    if subject is None:
        return candidate
    noun = SUBJECT_TYPOS.get(subject[2].lower(), subject[2])
    if noun.lower() in {"employee", "employees"}:
        return candidate[:command.end()] + re.sub(r"\bal\b", "all", subject[1], flags=re.IGNORECASE) + noun + candidate[command.end() + subject.end():]
    return candidate


def entry_agent(message: str) -> Agent:
    command = COMMAND.match(message)
    if not command or re.search(r"\b(?:and then|then)\b", message, re.IGNORECASE):
        return SUPERVISOR
    verb = command["verb"].lower()
    if verb in {"add", "create", "update", "edit"}:
        return AGENTS["write"]
    if verb in {"delete", "remove"}:
        return AGENTS["delete"]
    return AGENTS["read"]


async def resolve_delete_target(context: EmployeeContext, subject: str) -> dict:
    employee_id = EMPLOYEE_ID.fullmatch(subject) or re.fullmatch(r"(?:id\s*)?#?(\d+)", subject, re.IGNORECASE)
    if employee_id:
        await prepare_employee_deletion(context, int(employee_id[1]))
        return context.result

    name = re.sub(r"^(?:the\s+)?employee\s+(?:(?:named|with name)\s+)?", "", subject, flags=re.IGNORECASE).strip("\"' ")
    if not name or name.casefold() in {"employee", "employees", "all", "all employees", "the employee", "the employees", "everyone"}:
        return {"reply": "Which employee should I delete? Send one employee name or ID."}
    response = await context.client.get("/api/employees")
    response.raise_for_status()
    matches = [row for row in response.json() if row["name"].casefold() == name.casefold()]
    if not matches:
        return {"reply": f"No employee named {name} was found. Check the spelling or use their employee ID."}
    if len(matches) > 1:
        ids = ", ".join(str(row["id"]) for row in matches)
        return {"reply": f"More than one employee is named {name}. Specify one employee ID: {ids}."}
    await prepare_employee_deletion(context, matches[0]["id"])
    return context.result


def visible_output(output: object) -> str:
    text = re.split(r"</think\s*>", str(output or ""), flags=re.IGNORECASE)[-1]
    return re.split(r"<think\b[^>]*>", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def employee_draft(fields: dict) -> dict:
    try:
        draft = EmployeeInput.model_validate(fields).model_dump()
    except ValidationError:
        return {"reply": ADD_DETAILS}
    return {"reply": "Review the employee details, then select Save employee to add the record.", "employee_draft": draft}


def printed_tool_reply(answer: str, create_only: bool) -> dict | None:
    wrapped = re.fullmatch(r"(?:```(?:json)?\s*|<tool_call>\s*)(\{.*\})\s*(?:```|</tool_call>)", answer, re.DOTALL | re.IGNORECASE)
    text = wrapped[1] if wrapped else answer
    if not text.lstrip().startswith("{"):
        return None
    fallback = {"reply": "The assistant did not complete that request. No change was made. Try again or use the employee directory."}
    try:
        call = json.loads(text)
    except ValueError:
        return fallback
    if not isinstance(call, dict) or not create_only or call.get("name") not in ("add_employee", "save_employee"):
        return fallback
    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        return fallback
    return employee_draft(arguments)


def parse_add_fields(details: str) -> dict | None:
    positional = ADD_FIELDS.fullmatch(details)
    if positional:
        return {**positional.groupdict(), "salary": positional["salary"].replace(",", "")}
    labels = list(FIELD_LABEL.finditer(details))
    if not labels or labels[0].start() != 0:
        return None
    fields = {}
    for index, label in enumerate(labels):
        key = label[1].lower()
        if key == "desig":
            key = "designation"
        if key in fields:
            return {}
        end = labels[index + 1].start() if index + 1 < len(labels) else len(details)
        value = details[label.end():end].strip()
        if key == "salary" and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", value):
            value = value.replace(",", "")
        fields[key] = value
    return fields


async def run_supervisor(message: str, app: FastAPI, history: list | None = None):
    message = normalize_command(message)
    command = COMMAND.match(message)
    if command and ADD_WITHOUT_DETAILS.fullmatch(message[command.start("verb"):]):
        return {"reply": ADD_DETAILS}

    continuing_add = bool(not command and history and history[-1]["content"] == ADD_DETAILS)
    if continuing_add and message.casefold().rstrip(".!?") in {"cancel", "never mind", "nevermind"}:
        return {"reply": "Employee creation cancelled."}

    command_text = message[command.start("verb"):] if command else ""
    add_prefix = ADD_PREFIX.match(command_text)
    if continuing_add or add_prefix:
        details = message if continuing_add else command_text[add_prefix.end():]
        fields = parse_add_fields(details)
        if fields is not None:
            return employee_draft(fields)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://employee.local") as client:
        context = EmployeeContext(client, create_only=continuing_add or bool(command and command["verb"].lower() in {"add", "create"}))
        config = RunConfig(tracing_disabled=True)
        try:
            agent = AGENTS["write"] if continuing_add else entry_agent(message)
            if agent is not SUPERVISOR and command:
                subject = re.sub(r"\s+(?:for me|please)$", "", message[command.end():].strip().rstrip(".?!"), flags=re.IGNORECASE)
                if agent is AGENTS["delete"]:
                    return await resolve_delete_target(context, subject)
                if agent is AGENTS["read"]:
                    if LIST_EMPLOYEES.fullmatch(subject):
                        await lookup_employees(context, "")
                        return context.result
                    employee_id = EMPLOYEE_ID.fullmatch(subject)
                    if employee_id:
                        await lookup_employees(context, "", int(employee_id[1]))
                        return context.result
                    employee_name = EMPLOYEE_NAME.fullmatch(subject)
                    if employee_name:
                        await lookup_employees(context, employee_name[1].strip("\"'"))
                        return context.result
                message = message[command.start("verb"):]
            model_input = [*(history or []), {"role": "user", "content": message}] if history else message
            result = await Runner.run(agent, model_input, context=context, max_turns=3, run_config=config)
            if not context.started and result.last_agent is SUPERVISOR:
                label = visible_output(result.final_output).rstrip(".").casefold()
                specialist = next((agent for agent in AGENTS.values() if agent.name.casefold() == label), None)
                if specialist is None:
                    return {"reply": "Please give one employee request: list, find, add, update, or delete."}
                result = await Runner.run(specialist, model_input, context=context, max_turns=2, run_config=config)
        except APITimeoutError as exc:
            raise HTTPException(504, "The local model took too long. Use the directory controls to finish immediately.") from exc
        except APIConnectionError as exc:
            raise HTTPException(503, "Local Ollama is unavailable. Start it or use the directory controls.") from exc
        except NotFoundError as exc:
            raise HTTPException(503, f"Local model missing. Run ollama pull {MODEL_NAME}.") from exc
        if context.result is not None:
            return context.result
        answer = visible_output(result.final_output)
        tool_reply = printed_tool_reply(answer, context.create_only)
        if tool_reply is not None:
            return tool_reply
        if answer.rstrip(".").casefold() in {agent.name.casefold() for agent in AGENTS.values()}:
            answer = ""
        return {"reply": answer or "No final reply. Try an explicit request or use the directory controls."}