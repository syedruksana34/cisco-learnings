# Employee Management System

## MySQL setup

Create a MySQL database and grant your MySQL user permission to create tables and read and write data in it. For example, using a MySQL administrative account:

```sql
CREATE DATABASE employee_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

From this directory, install the dependencies and set the connection settings in your shell. The defaults are shown below; set `MYSQL_PASSWORD` securely in your environment if your account requires a password.

```sh
python3 -m venv .venv  # first-time setup only
.venv/bin/python -m pip install -r requirements.txt
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3306
export MYSQL_USER=root
export MYSQL_DATABASE=employee_management
.venv/bin/uvicorn employee:app --host 127.0.0.1 --port 8000
```

The application creates the `employees` table at startup if it does not exist. You can alternatively provide a SQLAlchemy `DATABASE_URL` such as `mysql+pymysql://user:password@localhost:3306/employee_management?charset=utf8mb4`; URL-encode special characters in credentials. Do not commit credentials to the repository.

Open http://127.0.0.1:8000/app for the interface or http://127.0.0.1:8000/docs for the API documentation. The database must be running and accessible before starting the application. Existing in-memory records are not automatically migrated.

## Separate Gemini chat app

The standalone chat app is in [python_with_ai](../python_with_ai/README.md) and
does not use or change the employee application. Follow its setup instructions
to configure a Gemini API key and run it separately.