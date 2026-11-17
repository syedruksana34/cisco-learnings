import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings

from campus.models import Course, Department, Enrollment, LoginAttempt, Student
from campus.services import RecordValidationError, save_record


@override_settings(RAG_ENABLED=False)
class CampusAPITest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "a-long-test-password"
        get_user_model().objects.create_user(username="admin", password=cls.password, is_staff=True)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.token = self.client.get("/api/session").json()["csrf_token"]
        response = self.client.post("/api/login", content_type="application/json", data={"username": "admin", "password": self.password}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.token = response.json()["csrf_token"]

    @property
    def headers(self):
        return {"X-CSRF-Token": self.token}

    def post(self, resource, data, status=201):
        response = self.client.post(f"/api/{resource}", content_type="application/json", data=data, headers=self.headers)
        self.assertEqual(response.status_code, status, response.content.decode())
        return response.json().get("data") if status == 201 else response

    def put(self, resource, record_id, data, status=200):
        response = self.client.put(f"/api/{resource}/{record_id}", content_type="application/json", data=data, headers=self.headers)
        self.assertEqual(response.status_code, status, response.content.decode())
        return response

    def delete(self, resource, record_id, status=204):
        response = self.client.delete(f"/api/{resource}/{record_id}", headers=self.headers)
        self.assertEqual(response.status_code, status, response.content.decode())
        return response

    def department(self):
        return self.post("departments", {"name": "Computer Science", "code": "CS"})

    @override_settings(ALLOW_OPEN_SIGNUP=True)
    def test_signup_immediate_access_and_login(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/session").json()["csrf_token"]
        payload = {"username": "new-admin", "password": "New-account-test-2026", "confirm_password": "New-account-test-2026"}
        response = client.post("/api/signup", data=payload, content_type="application/json", headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 201, response.content.decode())
        user = get_user_model().objects.get(username="new-admin")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(payload["password"]))
        self.assertNotEqual(user.password, payload["password"])
        self.assertEqual(client.get("/api/dashboard").status_code, 200)
        new_token = response.json()["csrf_token"]
        self.assertEqual(client.post("/api/logout", headers={"X-CSRF-Token": token}).status_code, 403)
        self.assertEqual(client.post("/api/logout", headers={"X-CSRF-Token": new_token}).status_code, 200)
        token = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/login", data={key: payload[key] for key in ("username", "password")}, content_type="application/json", headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200)

    @override_settings(ALLOW_OPEN_SIGNUP=True)
    def test_signup_validation_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/session").json()["csrf_token"]
        payload = {"username": "new-admin", "password": "New-account-test-2026", "confirm_password": "New-account-test-2026"}
        self.assertEqual(client.post("/api/signup", data=payload, content_type="application/json").status_code, 403)
        for changes in ({"username": ""}, {"username": "x" * 81}, {"username": "invalid name"}, {"username": "admin"}, {"password": "short", "confirm_password": "short"}, {"confirm_password": "different"}, {"password": None}, {"is_superuser": True}):
            response = client.post("/api/signup", data={**payload, **changes}, content_type="application/json", headers={"X-CSRF-Token": token})
            self.assertEqual(response.status_code, 400, response.content.decode())
        self.assertFalse(get_user_model().objects.filter(username="new-admin").exists())
        self.assertEqual(self.client.post("/api/signup", data=payload, content_type="application/json", headers=self.headers).status_code, 409)

    @override_settings(ALLOW_OPEN_SIGNUP=False)
    def test_signup_can_be_disabled(self):
        response = self.client.post("/api/signup", data={}, content_type="application/json", headers=self.headers)
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(self.client.get("/"), 'id="auth-switch"')

    def student_data(self, department_id):
        return {"student_number": "S001", "first_name": "Ava", "last_name": "Chen",
                "email": "AVA@EXAMPLE.EDU", "department_id": department_id, "year": 1, "status": "Active"}

    def academic_records(self, capacity=2):
        dept = self.department()
        student = self.post("students", self.student_data(dept["id"]))
        faculty = self.post("faculty", {"employee_number": "F001", "first_name": "Jane", "last_name": "Doe",
                                      "email": "jane@example.edu", "department_id": dept["id"], "title": "Professor"})
        course = self.post("courses", {"code": "CS101", "name": "Computing", "department_id": dept["id"],
                                      "faculty_id": faculty["id"], "credits": 3, "capacity": capacity})
        enrollment = self.post("enrollments", {"student_id": student["id"], "course_id": course["id"], "semester": "Fall 2026", "status": "Enrolled"})
        return dept, student, faculty, course, enrollment

    def test_authentication_and_csrf(self):
        anonymous = Client(enforce_csrf_checks=True)
        self.assertEqual(anonymous.get("/api/students").status_code, 401)
        self.assertEqual(anonymous.get("/api/dashboard").status_code, 401)
        self.assertEqual(anonymous.get("/api/export/students").status_code, 401)
        self.assertEqual(anonymous.post("/api/login", content_type="application/json", data={}).status_code, 403)
        self.assertEqual(self.client.post("/api/departments", content_type="application/json", data={}, headers={"X-CSRF-Token": "caf\u00e9"}).status_code, 403)
        response = self.client.post("/api/logout", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/students").status_code, 401)
        self.assertEqual(self.client.post("/api/departments", content_type="application/json", data={}, headers=self.headers).status_code, 403)

    def test_student_and_faculty_contact_numbers(self):
        dept = self.department()
        payloads = {
            "students": self.student_data(dept["id"]),
            "faculty": {"employee_number": "F001", "first_name": "Jane", "last_name": "Doe",
                        "email": "jane@example.edu", "department_id": dept["id"], "title": "Professor"},
        }
        for resource, payload in payloads.items():
            with self.subTest(resource=resource):
                phone = "9876543210"
                created = self.post(resource, {**payload, "phone_number": f" {phone} "})
                record_id = created["id"]
                self.assertEqual(created["phone_number"], phone)
                self.assertEqual(self.client.get(f"/api/{resource}/{record_id}").json()["data"]["phone_number"], phone)
                self.assertEqual(self.client.get(f"/api/{resource}?q=98765").json()["total"], 1)
                exported = list(csv.DictReader(io.StringIO(self.client.get(f"/api/export/{resource}").content.decode())))
                self.assertEqual(exported[0]["phone_number"], phone)
                updated = self.put(resource, record_id, {**payload, "phone_number": "0012345678"}).json()["data"]
                self.assertEqual(updated["phone_number"], "0012345678")
                preserved = self.put(resource, record_id, payload).json()["data"]
                self.assertEqual(preserved["phone_number"], "0012345678")
                for invalid in ("123456789", "12345678901", "+919876543210", "98765 43210", "98765-43210", "abcdefghij", "１２３４５６７８９０", "123456", "1" * 16, "abc9876543210", "91+9876543210", 9876543210, None):
                    self.put(resource, record_id, {**payload, "phone_number": invalid}, 400)
                for valid in ("1234567890", "0001234567", ""):
                    result = self.put(resource, record_id, {**payload, "phone_number": valid}).json()["data"]
                    self.assertEqual(result["phone_number"], valid)
                self.delete(resource, record_id)
                blank = self.post(resource, payload)
                self.assertEqual(blank["phone_number"], "")

    def chat(self, message):
        response = self.client.post("/api/chatbot", data={"message": message}, content_type="application/json", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response.json()["mode"], "local")
        self.assertEqual(set(response.json()), {"reply", "links", "mode"})
        return response.json()

    def test_chatbot_authentication_csrf_and_validation(self):
        anonymous = Client(enforce_csrf_checks=True)
        token = anonymous.get("/api/session").json()["csrf_token"]
        response = anonymous.post("/api/chatbot", data={"message": "summary"}, content_type="application/json", headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post("/api/chatbot", data={"message": "summary"}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client.get("/api/chatbot").status_code, 405)
        for data in ({}, {"message": ""}, {"message": " "}, {"message": 123}, {"message": "x" * 501}, {"message": "summary", "extra": True}):
            response = self.client.post("/api/chatbot", data=data, content_type="application/json", headers=self.headers)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.chat("x" * 500)["mode"], "local")

    def test_chatbot_live_counts_and_workflow_help(self):
        self.academic_records()
        answer = self.chat("How many students and faculty are there?")
        self.assertIn("Students: 1", answer["reply"])
        self.assertIn("Faculty: 1", answer["reply"])
        self.assertEqual([link["page"] for link in answer["links"]], ["students", "faculty"])
        self.assertIn("exactly 10 digits", self.chat("How do I add a student?")["reply"])
        self.assertIn("cumulative", self.chat("How do I record a fee payment?")["reply"])
        self.assertIn("every record", self.chat("How do I export CSV?")["reply"])
        self.assertIn("Computer Science: 1 students", self.chat("Department distribution")["reply"])
        self.assertEqual(self.chat("Open faculty")["links"], [{"label": "Faculty", "page": "faculty"}])
        self.assertIn("Courses: 1", self.chat("Campus summary")["reply"])

    def test_chatbot_understands_conversation_synonyms_and_typos(self):
        self.academic_records()
        greetings = self.chat("Hi, how are you today?")["reply"]
        self.assertIn("doing well", greetings)
        self.assertIn("Good to hear", self.chat("gud mrning, can i see attendence?")["reply"])
        self.assertEqual(self.chat("gud mrning, can i see attendence?")["links"][0]["page"], "attendance")
        self.assertIn("Students: 1", self.chat("can u tell me how many students do we got?")["reply"])
        self.assertIn("Students: 1", self.chat("How many studnts are there?")["reply"])
        self.assertIn("Outstanding:", self.chat("whats the fee balence?")["reply"])
        self.assertEqual(self.chat("Can I see the teachers?")["links"][0]["page"], "faculty")
        self.assertIn("To add a student", self.chat("I want to add a student")["reply"])
        self.assertIn("To add a student", self.chat("Please add a student")["reply"])
        self.assertIn("cannot delete records in chat", self.chat("Delete all students")["reply"])
        self.assertIn("not sure I understood", self.chat("Tell me about quantum physics")["reply"])
        self.assertIn("Students: 1", self.chat("How many studens are there?")["reply"])

    def test_chatbot_finance_attendance_and_read_only_limits(self):
        _, student, _, _, enrollment = self.academic_records()
        self.assertIn("No attendance", self.chat("Attendance rate")["reply"])
        self.post("attendance", {"enrollment_id": enrollment["id"], "date": date.today().isoformat(), "status": "Late"})
        self.assertIn("100%", self.chat("Attendance rate")["reply"])
        self.post("fees", {"student_id": student["id"], "description": "Tuition", "amount_cents": 123456, "paid_cents": 23456, "due_date": (date.today() - timedelta(days=1)).isoformat()})
        answer = self.chat("Outstanding fees")["reply"]
        self.assertIn("Outstanding: $1,000.00", answer)
        self.assertIn("Overdue unpaid fee records: 1", answer)
        self.assertNotIn(student["email"], answer)
        for message in ("Delete all students", "Update faculty", "Pay fees", "Create a course"):
            self.assertIn("cannot", self.chat(message)["reply"])
        self.assertEqual(self.client.get("/api/students").json()["total"], 1)
        self.assertIn("not sure I understood", self.chat("Tell me about quantum physics")["reply"])
        self.assertIn("not a generative AI", self.chat("hello")["reply"])
        response = self.client.post("/api/chatbot", data={"message": "<script>alert(1)</script>"}, content_type="application/json", headers=self.headers)
        self.assertNotIn("<script>", response.json()["reply"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_bad_password_and_lockout(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/session").json()["csrf_token"]
        headers = {"X-CSRF-Token": token}
        for _ in range(10):
            self.assertEqual(client.post("/api/login", content_type="application/json", data={"username": "admin", "password": "wrong"}, headers=headers).status_code, 401)
        self.assertEqual(client.post("/api/login", content_type="application/json", data={"username": "admin", "password": self.password}, headers=headers).status_code, 429)

    def test_crud_all_resources_and_relationships(self):
        dept, student, faculty, course, enrollment = self.academic_records()
        self.assertEqual(student["email"], "ava@example.edu")
        attendance = self.post("attendance", {"enrollment_id": enrollment["id"], "date": date.today().isoformat(), "status": "Present"})
        fee = self.post("fees", {"student_id": student["id"], "description": "Tuition", "amount_cents": 100000, "paid_cents": 25000, "due_date": "2026-12-01"})
        items = {"departments": dept, "students": student, "faculty": faculty, "courses": course, "enrollments": enrollment, "attendance": attendance, "fees": fee}
        for resource, item in items.items():
            with self.subTest(resource=resource):
                self.assertEqual(self.client.get(f"/api/{resource}").json()["total"], 1)
                self.assertEqual(self.client.get(f"/api/{resource}/{item['id']}").json()["data"]["id"], item["id"])
                self.put(resource, item["id"], {key: value for key, value in item.items() if key != "id"})
        self.delete("students", student["id"], 409)
        self.delete("departments", dept["id"], 409)
        self.delete("courses", course["id"], 409)
        self.delete("faculty", faculty["id"], 409)
        self.delete("enrollments", enrollment["id"], 409)
        for resource in ("attendance", "fees", "enrollments", "courses", "faculty", "students", "departments"):
            self.delete(resource, items[resource]["id"])
            self.assertEqual(self.client.get(f"/api/{resource}").json()["total"], 0)

    def test_duplicate_and_invalid_reference(self):
        dept = self.department()
        self.post("departments", {"name": "Computer Science", "code": "CS"}, 409)
        data = self.student_data(999)
        self.post("students", data, 400)
        data["department_id"] = dept["id"]
        self.post("students", data)
        self.post("students", data, 409)

    def test_mysql_preserves_case_sensitive_identifiers(self):
        self.department()
        self.post("departments", {"name": "computer science", "code": "cs"})
        self.assertEqual(self.client.get("/api/departments").json()["total"], 2)

    def test_validation_rejects_bad_inputs(self):
        dept = self.department()
        for changes in ({"year": True}, {"year": 1.5}, {"year": 9}, {"first_name": " "}, {"email": "bad@email"}, {"status": "unknown"}, {"unknown": "value"}, {"department_id": "1"}, {"first_name": "a" * 201}):
            with self.subTest(changes=changes):
                self.post("students", {**self.student_data(dept["id"]), **changes}, 400)
        self.post("students", {}, 400)
        response = self.client.post("/api/students", content_type="application/json", data=[], headers=self.headers)
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/students", data="{broken", content_type="application/json", headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_capacity_and_semester_rules(self):
        dept, _, _, course, enrollment = self.academic_records(capacity=1)
        data = self.student_data(dept["id"])
        data.update(student_number="S002", email="other@example.edu")
        student = self.post("students", data)
        second = {"student_id": student["id"], "course_id": course["id"], "semester": "Fall 2026", "status": "Enrolled"}
        self.post("enrollments", second, 400)
        second["semester"] = "Spring 2027"
        self.post("enrollments", second)
        second["semester"] = "Fall 2026"
        second["status"] = "Dropped"
        dropped = self.post("enrollments", second)
        self.put("enrollments", dropped["id"], {**second, "status": "Enrolled"}, 400)
        self.put("enrollments", enrollment["id"], {key: ("Dropped" if key == "status" else value) for key, value in enrollment.items() if key != "id"})
        self.put("enrollments", dropped["id"], {**second, "status": "Enrolled"})

    def test_capacity_cannot_be_reduced_below_enrollment(self):
        dept, _, _, course, _ = self.academic_records()
        student = self.post("students", {**self.student_data(dept["id"]), "student_number": "S002", "email": "two@example.edu"})
        self.post("enrollments", {"student_id": student["id"], "course_id": course["id"], "semester": "Fall 2026", "status": "Enrolled"})
        self.put("courses", course["id"], {**{k: v for k, v in course.items() if k != "id"}, "capacity": 1}, 400)

    def test_inactive_students_cannot_enroll(self):
        _, student, _, course, _ = self.academic_records()
        self.put("students", student["id"], {**{k: v for k, v in student.items() if k != "id"}, "status": "On leave"})
        self.post("enrollments", {"student_id": student["id"], "course_id": course["id"], "semester": "Spring 2027", "status": "Enrolled"}, 400)

    def test_attendance_validation_and_history(self):
        _, _, _, _, enrollment = self.academic_records()
        payload = {"enrollment_id": enrollment["id"], "date": date.today().isoformat(), "status": "Present"}
        self.post("attendance", payload)
        self.post("attendance", payload, 409)
        self.post("attendance", {**payload, "date": (date.today() + timedelta(days=1)).isoformat()}, 400)
        self.post("attendance", {**payload, "date": "2026-02-30"}, 400)
        self.post("attendance", {**payload, "date": "20260101"}, 400)
        update = {k: v for k, v in enrollment.items() if k != "id"}
        self.put("enrollments", enrollment["id"], {**update, "semester": "Spring 2027"}, 400)
        self.put("enrollments", enrollment["id"], {**update, "status": "Dropped"})
        self.post("attendance", {**payload, "date": (date.today() - timedelta(days=1)).isoformat()}, 400)

    def test_fee_validation_and_dashboard_totals(self):
        _, student, _, _, enrollment = self.academic_records()
        payload = {"student_id": student["id"], "description": "Tuition", "amount_cents": 10000, "paid_cents": 3000, "due_date": "2026-12-01"}
        for changes in ({"paid_cents": 10001}, {"amount_cents": 0}, {"paid_cents": -1}, {"amount_cents": 12.34}, {"due_date": "yesterday"}):
            self.post("fees", {**payload, **changes}, 400)
        self.post("fees", payload)
        for day, status in enumerate(("Present", "Absent", "Late", "Excused")):
            self.post("attendance", {"enrollment_id": enrollment["id"], "date": (date.today() - timedelta(days=day)).isoformat(), "status": status})
        data = self.client.get("/api/dashboard").json()
        self.assertEqual(data["finance"], {"total_cents": 10000, "paid_cents": 3000})
        self.assertEqual(data["attendance"], {"total": 4, "attended": 2})
        self.assertEqual(data["counts"]["students"], 1)
        self.assertEqual(data["departments"][0]["count"], 1)
        self.assertEqual(data["outstanding_fees"][0]["student"], "Ava Chen")
        self.assertEqual(self.client.get("/api/fees").json()["data"][0]["balance_cents"], 7000)

    def test_filters_export_and_formula_safety(self):
        dept = self.department()
        self.post("students", self.student_data(dept["id"]))
        self.assertEqual(self.client.get("/api/students?q=ava").json()["total"], 1)
        self.assertEqual(self.client.get("/api/students?status=On%20leave").json()["total"], 0)
        self.assertEqual(self.client.get(f"/api/students?department_id={dept['id']}").json()["total"], 1)
        self.assertEqual(self.client.get("/api/students?q=';DROP%20TABLE%20students").json()["total"], 0)
        self.post("departments", {"name": "=HYPERLINK(\"bad\")", "code": "BAD"})
        response = self.client.get("/api/export/departments")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        exported = list(csv.DictReader(io.StringIO(response.content.decode())))
        self.assertTrue(exported[0]["name"].startswith("'="))

    def test_unknown_routes_and_missing_records(self):
        self.assertEqual(self.client.get("/api/unknown").status_code, 404)
        self.assertIn("error", self.client.get("/api/no/such/endpoint").json())
        self.assertEqual(self.client.get("/api/students/999").status_code, 404)
        self.put("departments", 999, {"name": "A", "code": "A"}, 404)
        self.delete("departments", 999, 404)

    def test_empty_dashboard_and_csv(self):
        data = self.client.get("/api/dashboard").json()
        self.assertEqual(data["finance"], {"total_cents": 0, "paid_cents": 0})
        self.assertEqual(data["attendance"], {"total": 0, "attended": 0})
        self.assertEqual(data["recent_students"], [])
        self.assertEqual(self.client.get("/api/export/students").status_code, 200)

    def test_security_headers_and_template(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"CampusFlow", response.content)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(self.client.get("/api/session").headers["Cache-Control"], "no-store")

    def test_initialization_and_demo_commands(self):
        call_command("seed_demo", stdout=io.StringIO())
        data = self.client.get("/api/dashboard").json()
        self.assertEqual(data["counts"]["students"], 12)
        self.assertEqual(data["counts"]["attendance"], 60)
        self.assertEqual(data["counts"]["courses"], 5)
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=io.StringIO())
        self.assertEqual(self.client.get("/api/students").json()["total"], 12)

    def test_create_admin_command(self):
        for username, password in (("new", "short"), ("admin", self.password)):
            with patch("campus.management.commands.create_admin.getpass", return_value=password), self.assertRaises(CommandError):
                call_command("create_admin", username=username, stdout=io.StringIO())
        with patch("campus.management.commands.create_admin.getpass", return_value=self.password):
            call_command("create_admin", username="new", stdout=io.StringIO())
        user = get_user_model().objects.get(username="new")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password(self.password))
        self.assertNotEqual(user.password, self.password)

    def test_database_and_cookie_settings(self):
        self.assertEqual(connection.vendor, "mysql")
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.mysql")
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 60 * 60)

    def test_csrf_rotation_and_non_admin_access(self):
        client = Client(enforce_csrf_checks=True)
        old_token = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/login", data={"username": "admin", "password": self.password}, content_type="application/json", headers={"X-CSRF-Token": old_token})
        new_token = response.json()["csrf_token"]
        self.assertNotEqual(old_token, new_token)
        self.assertEqual(client.post("/api/departments", data={"name": "A", "code": "A"}, content_type="application/json", headers={"X-CSRF-Token": old_token}).status_code, 403)
        get_user_model().objects.create_user(username="student", password=self.password)
        response = client.post("/api/login", data={"username": "student", "password": self.password}, content_type="application/json", headers={"X-CSRF-Token": new_token})
        self.assertEqual(response.status_code, 401)

    def test_lockout_expires(self):
        from django.utils import timezone
        LoginAttempt.objects.create(username="expired", failures=10, window_start=timezone.now() - timedelta(minutes=16))
        self.client.post("/api/login", data={"username": "expired", "password": "wrong"}, content_type="application/json", headers=self.headers)
        self.assertEqual(LoginAttempt.objects.get(username="expired").failures, 1)

    def test_methods_and_oversized_requests(self):
        response = self.client.patch("/api/students/1", data="{}", content_type="application/json", headers=self.headers)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers["Allow"], "GET, PUT, DELETE")
        response = self.client.post("/api/departments", data='{"name":"' + "x" * 70000 + '"}', content_type="application/json", headers=self.headers)
        self.assertEqual(response.status_code, 413)

class EnrollmentConcurrencyTest(TransactionTestCase):
    def test_mysql_serializes_last_seat_enrollment(self):
        department = Department.objects.create(name="Concurrency", code="LOCK")
        course = Course.objects.create(code="LOCK101", name="Last seat", department=department, credits=3, capacity=1)
        students = [
            Student.objects.create(
                student_number=f"LOCK{index}", first_name="Concurrent", last_name=str(index),
                email=f"lock{index}@example.edu", department=department, year=1, status="Active",
            )
            for index in range(2)
        ]
        barrier = Barrier(2)

        def enroll(student_id):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                save_record("enrollments", {"student_id": student_id, "course_id": course.pk, "semester": "Fall 2026", "status": "Enrolled"})
                return "created"
            except RecordValidationError as exc:
                return str(exc)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(enroll, [student.pk for student in students]))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("This course is at capacity for the selected semester."), 1)
        self.assertEqual(Enrollment.objects.filter(course=course, status="Enrolled").count(), 1)
