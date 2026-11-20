"""A small Flask to-do list with tasks stored in memory."""

from datetime import date

from flask import Flask, flash, redirect, render_template, request, url_for


app = Flask(__name__)
app.secret_key = "todo-demo-local-development"
tasks = []


def count_tasks_by_priority(tasks, priority):
    """Count tasks with the given priority.

    Args:
        tasks: Task dictionaries containing a priority key.
        priority: Priority to count.

    Returns:
        The number of tasks with the specified priority.
    """
    count = 0
    for task in tasks:
        if task["priority"] == priority:
            count += 1
    return count


@app.get("/")
def index():
    """Display tasks sorted by due date while retaining their original indexes."""
    sorted_tasks = sorted(enumerate(tasks), key=lambda item: item[1]["due_date"])
    return render_template("index.html", tasks=sorted_tasks)


@app.post("/add")
def add_task():
    """Validate the submitted fields and add a task to the in-memory list."""
    task_name = request.form.get("task", "").strip()
    priority = request.form.get("priority", "")
    category = request.form.get("category", "")
    due_date = request.form.get("due_date", "")

    try:
        parsed_date = date.fromisoformat(due_date)
        valid_date = parsed_date.isoformat() == due_date
    except ValueError:
        valid_date = False

    if not task_name or priority not in {"High", "Medium", "Low"} or category not in {"Work", "Personal", "Health"} or not valid_date:
        flash("Enter a task name, priority, category, and valid due date.")
        return redirect(url_for("index"))

    tasks.append({"task": task_name, "priority": priority, "category": category, "due_date": due_date})
    return redirect(url_for("index"))


@app.post("/delete/<int:task_index>")
def delete_task(task_index):
    """Delete the task at its original list index, if it exists.

    Args:
        task_index: Index of the task in the in-memory list.
    """
    if 0 <= task_index < len(tasks):
        tasks.pop(task_index)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(port=9000)