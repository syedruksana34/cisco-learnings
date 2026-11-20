# To-do list

A small Flask application for adding and deleting tasks with a priority, category, and due date. Tasks are displayed in due-date order and stored in memory, so they disappear when the server restarts. This is a local learning demo, not a production or multi-user application.

## Setup

Python 3.10 or later is required. From this directory, create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, use these commands instead:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open http://127.0.0.1:9000 and press Ctrl+C in the terminal to stop the server.

## Test

```bash
python -m pytest test_app.py -v
```

The tests cover `count_tasks_by_priority`, due-date sorting, deletion, and invalid input. In the lesson's intentional bug, `count =+ 1` assigns positive one on every match; `count += 1` correctly increments the count.