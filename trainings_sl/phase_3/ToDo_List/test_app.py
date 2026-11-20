"""Tests for the to-do list demo."""

import pytest

from app import app, count_tasks_by_priority, tasks


def test_count_empty_tasks():
    assert count_tasks_by_priority([], "High") == 0


def test_count_one_matching_task():
    assert count_tasks_by_priority([{"priority": "High"}], "High") == 1


def test_count_several_matching_tasks():
    items = [{"priority": "High"}, {"priority": "Low"}, {"priority": "High"}]
    assert count_tasks_by_priority(items, "High") == 2


def test_count_no_matching_tasks():
    assert count_tasks_by_priority([{"priority": "Low"}], "High") == 0


@pytest.fixture
def client():
    tasks.clear()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client
    tasks.clear()


def test_tasks_are_sorted_and_delete_uses_original_index(client):
    client.post("/add", data={"task": "Later", "priority": "Low", "category": "Personal", "due_date": "2026-12-10"})
    client.post("/add", data={"task": "Sooner", "priority": "High", "category": "Work", "due_date": "2026-11-20"})
    response = client.get("/")
    assert response.data.index(b"Sooner") < response.data.index(b"Later")
    client.post("/delete/1")
    assert [task["task"] for task in tasks] == ["Later"]


def test_invalid_task_is_not_added(client):
    response = client.post("/add", data={"task": "  ", "priority": "High", "category": "Work", "due_date": "not-a-date"}, follow_redirects=True)
    assert b"valid due date" in response.data
    assert tasks == []