# Employee Operations

This local demo has a FastAPI REST API, its own SQLite database, and a single Supervisor Agent in the browser. The supervisor delegates to three internal Ollama-backed specialists through the `/api/supervisor` endpoint. No API key is needed.

| Agent | Example | Capability |
| --- | --- | --- |
| Read | `Find employees named Alex` | List, search, or read an employee by ID |
| Write | `Add Alex Lee, designation Analyst, age 28, salary 50000` | Create or replace an employee's fields |
| Delete | `Prepare deletion for employee ID 1` | Preview a deletion; only browser confirmation deletes the record |

With Ollama installed and serving on `127.0.0.1:11434`, run from the workspace root:

```bash
ollama pull qwen3:1.7b
python -m pip install -r agentic_ai/multi_agent/requirements.txt
python -m uvicorn agentic_ai.multi_agent.api:app --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001/> or <http://127.0.0.1:8001/docs>. Directory controls work even when Ollama is offline. To use another local tool-capable model, set `OLLAMA_MODEL` before starting the server.

The directory starts empty. Records are stored in the ignored `employees.sqlite3` file. This demo has no user authentication; keep it on localhost.