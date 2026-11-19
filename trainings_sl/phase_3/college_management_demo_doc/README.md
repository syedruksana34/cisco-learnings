# College Management API

Lesson 01 Demo 04: a FastAPI scaffold with SQLAlchemy 2.0, Pydantic v2, and SQLite.

## Run locally

Open this folder in VS Code. In a Linux/macOS terminal, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

In Windows PowerShell, create the environment with `py -m venv .venv` and activate it with `.\.venv\Scripts\Activate.ps1`, then run the same install and server commands. If script execution is blocked, use `.\.venv\Scripts\python.exe` in place of `python` instead of activating.

Visit [Swagger UI](http://127.0.0.1:8000/docs). The app creates `college.db` next to `database.py` on first startup and reuses it on subsequent runs. Stop the server with Ctrl+C.

## Validate in Swagger

| Request | Example body | Expected result |
|---|---|---|
| `GET /` | | `200` with `{"status":"College Management API is running"}` |
| `POST /api/departments/` | `{"department_name":"Computer Science"}` | `201` with the generated `department_id` and the department name |
| `POST /api/departments/` | `{"department_name":"Mechanical Engineering"}` | `201` with the generated `department_id` and the department name |
| `GET /api/departments/` | | `200` with both departments |
| `POST /api/students/` | `{"student_name":"Asha Rao","department_id":1}` | `201` with both IDs and both names; the department name is `Computer Science` |
| `POST /api/students/` | `{"student_name":"Rahul Mehta","department_id":2}` | `201` with both IDs and both names; the department name is `Mechanical Engineering` |
| `GET /api/students/` | | `200` with both students and their department names |
| `POST /api/students/` | `{"student_name":"Ram","department_id":10}` | `404` with `{"detail":"Department not found"}` if department `10` does not exist |

Use the department IDs returned by the POST requests when testing against a database that already contains rows. For the 404 check, choose an ID not listed by `GET /api/departments/`.

## Line-by-line scaffold review

Blank lines separate imports, declarations, and logical steps; they do not execute. In VS Code Ask mode, attach the relevant files and compare the explanation with the source below.

### [database.py](database.py)

| Line | What it does and why |
|---|---|
| 1 | Imports `Iterator` to type the session dependency's generator. |
| 2 | Imports `Path` to build a database path independent of the working directory. |
| 3 | Imports `Annotated` so the session type can carry FastAPI dependency metadata. |
| 5 | Imports `Depends` to register the session provider on route parameters. |
| 6 | Imports tools to construct the SQLite URL, create an engine, and listen for new connections. |
| 7 | Imports the ORM base class, session type, and session factory builder. |
| 9 | Locates `college.db` alongside this module. |
| 10 | Creates an engine that manages connections to that file. |
| 11 | Binds a factory for new sessions to that engine. |
| 14 | Registers a hook that runs for each new physical connection. |
| 15 | Receives the SQLite connection and the unused SQLAlchemy connection record. |
| 16 | Explains why declaring a foreign key in the ORM is not enough for SQLite. |
| 17 | Opens a cursor to send the SQLite setting. |
| 18 | Starts a block with guaranteed cursor cleanup. |
| 19 | Enables foreign-key enforcement on this connection. |
| 20 | Runs cleanup even if the statement raises an error. |
| 21 | Closes the cursor without closing the pooled connection. |
| 24 | Defines the shared declarative base that holds the ORM table metadata. |
| 25 | Leaves the base otherwise unchanged. |
| 28 | Defines the generator FastAPI uses to supply request sessions. |
| 29 | Opens a fresh session in a context manager that closes it on exit, even on errors. |
| 30 | Hands the session to the route until FastAPI tears down the dependency. |
| 33 | Gives both routers a reusable dependency type without making a session a request-body field. |

### [models.py](models.py)

| Line | What it does and why |
|---|---|
| 1 | Postpones annotation evaluation so `Department` can refer to `Student` before it is defined. |
| 3 | Imports `ForeignKey` to declare the database constraint. |
| 4 | Imports the ORM annotation and helpers for mapped columns and relationships. |
| 6 | Imports the shared base so startup can create both tables from its metadata. |
| 9 | Maps the `Department` class. |
| 10 | Sets its table name to `departments`. |
| 12 | Declares the integer primary key; SQLite generates its value when omitted. |
| 13 | Declares a non-null department name column; SQLAlchemy infers its type from `str`. |
| 14 | Maps the department's student collection and links it to `Student.department`. |
| 17 | Maps the `Student` class. |
| 18 | Sets its table name to `students`. |
| 20 | Declares the integer primary key for students. |
| 21 | Declares the non-null student name column. |
| 22 | Makes `department_id` a required foreign key to `departments.department_id`. |
| 23 | Maps the related department and links it back to `Department.students`. |
| 25 | Makes the computed department name readable as an attribute. |
| 26 | Declares the property and its string return type. |
| 27 | Reads the name from the related department rather than duplicating it in the students table. |

### [schemas.py](schemas.py)

| Line | What it does and why |
|---|---|
| 1 | Imports Pydantic's base model and configuration helper. |
| 4 | Defines the request body for adding a department. |
| 5 | Requires a department name string without asking for a generated ID. |
| 8 | Reuses the department name field in the response schema. |
| 9 | Allows response validation to read values from ORM attributes. |
| 11 | Adds the generated department ID to the response. |
| 14 | Defines the request body for adding a student. |
| 15 | Requires a student name string. |
| 16 | Requires an integer ID for the department the student should join. |
| 19 | Reuses the student name and department ID in the response. |
| 20 | Allows validation to read the ORM attributes, including computed properties. |
| 22 | Adds the generated student ID to the response. |
| 23 | Includes the related department's name in the response. |

### [routers/departments.py](routers/departments.py)

| Line | What it does and why |
|---|---|
| 1 | Imports the router class and named HTTP status constants. |
| 2 | Imports the SQLAlchemy statement builder for listing rows. |
| 4 | Imports the per-request session dependency. |
| 5 | Imports the mapped department class used for reads and inserts. |
| 6 | Imports the request and response schemas. |
| 8 | Sets the URL prefix and groups the routes under `departments` in Swagger. |
| 11 | Registers the collection GET and declares its array response schema. |
| 12 | Defines the handler with an injected session. |
| 13 | Fetches ORM objects sorted by department ID for a stable list order. |
| 14 | Validates and converts each object into the public response schema. |
| 17 | Registers the collection POST and declares its response and `201 Created` status. |
| 18 | Receives a validated request body and an injected session. |
| 19 | Constructs a department row from the submitted name. |
| 20 | Adds it to the session so it will be inserted. |
| 21 | Commits the transaction to persist the row. |
| 22 | Reloads the row, including its generated ID. |
| 23 | Converts the stored department into the public response. |

### [routers/students.py](routers/students.py)

| Line | What it does and why |
|---|---|
| 1 | Imports routing, HTTP errors, and named status constants. |
| 2 | Imports the SQLAlchemy statement builder. |
| 3 | Imports the loader that fetches related departments in the same query. |
| 5 | Imports the per-request session dependency. |
| 6 | Imports both mapped classes for lookup, listing, and insertion. |
| 7 | Imports student request and response schemas. |
| 9 | Sets the URL prefix and groups the routes under `students` in Swagger. |
| 12 | Registers the collection GET and declares its array response schema. |
| 13 | Defines the list handler with an injected session. |
| 14 | Starts building a multiline query. |
| 15 | Selects mapped students. |
| 16 | Eager-loads the department so serialization does not trigger a query per student. |
| 17 | Orders students by ID for a stable list order. |
| 18 | Closes the multiline expression; it has not executed yet. |
| 19 | Executes the query and converts ORM objects to responses while the session is open. |
| 22 | Registers the collection POST and declares its response and `201 Created` status. |
| 23 | Receives a validated request body and an injected session. |
| 24 | Looks up the department by its primary key. |
| 25 | Checks whether the lookup missed. |
| 26 | Aborts before attempting an insert when the department does not exist. |
| 27 | Sets the HTTP status to `404 Not Found`. |
| 28 | Sets the error message returned under `detail`. |
| 29 | Closes the exception constructor. |
| 31 | Builds a student linked to the fetched department; the ORM sets the foreign key. |
| 32 | Adds the student to the session for insertion. |
| 33 | Commits the transaction to persist the student. |
| 34 | Reloads the saved row, including its generated ID. |
| 35 | Builds the response with the related department name before the session closes. |

### [main.py](main.py)

| Line | What it does and why |
|---|---|
| 1 | Imports the type for the async generator used by the lifespan hook. |
| 2 | Imports the decorator that turns the generator into an async context manager. |
| 4 | Imports the application class. |
| 6 | Imports the shared table metadata via `Base` and the engine that runs the DDL. |
| 7 | Imports the routers, which also load the models and register their tables on `Base.metadata`. |
| 10 | Wraps the lifespan hook as the async context manager FastAPI expects. |
| 11 | Declares the hook and accepts the unused app argument. |
| 12 | Creates missing tables before the server starts accepting requests. |
| 13 | Yields control to the running app; this demo has no custom shutdown step. |
| 16 | Instantiates the app with its Swagger title and startup hook. |
| 17 | Includes the department router. |
| 18 | Includes the student router. |
| 21 | Registers `GET /` as a basic liveness endpoint. |
| 22 | Defines a handler that returns a dictionary with string keys and values. |
| 23 | Returns the status message as JSON; it does not check database health. |

### Supporting files

- [routers/__init__.py](routers/__init__.py), line 1: marks the folder as a regular Python package and documents its purpose.
- [requirements.txt](requirements.txt), lines 1-4: declare FastAPI for routing, Uvicorn (with standard extras) for serving and reload, SQLAlchemy 2.0 for persistence, and Pydantic v2 for validation and serialization, respectively.
- [.gitignore](.gitignore), lines 1-3: exclude the local virtual environment, Python bytecode cache directories, and this demo's SQLite file, respectively.

For this local demo, `create_all()` is enough to create missing tables, but it does not migrate an existing schema. The list endpoints are unpaginated, the API has no authentication, and name fields do not enforce business rules such as non-empty or unique names.
