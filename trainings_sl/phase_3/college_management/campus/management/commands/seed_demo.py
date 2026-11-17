from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from campus.models import Attendance, Course, Department, Enrollment, Faculty, Fee, Student
from campus.services import RESOURCES


class Command(BaseCommand):
    help = "Add synthetic demo records to empty management tables."

    @transaction.atomic
    def handle(self, *args, **options):
        if any(model.objects.exists() for model, _ in RESOURCES.values()):
            raise CommandError("Demo data requires empty management tables; existing data was not changed.")
        departments = [
            Department.objects.create(name=name, code=code)
            for name, code in [
                ("Computer Science", "CS"), ("Business Administration", "BUS"),
                ("Mechanical Engineering", "ME"), ("Arts & Humanities", "ART"),
            ]
        ]
        people = [
            ("Ava", "Thompson", 1), ("Liam", "Patel", 2), ("Olivia", "Chen", 1),
            ("Noah", "Williams", 3), ("Emma", "Garcia", 4), ("Elijah", "Wilson", 2),
            ("Sophia", "Ahmed", 1), ("James", "Kim", 3), ("Isabella", "Davis", 4),
            ("Lucas", "Martin", 1), ("Mia", "Robinson", 2), ("Amir", "Hassan", 3),
        ]
        faculty = [
            Faculty.objects.create(
                employee_number=f"FAC-{index:03}", first_name=first, last_name=last,
                email=f"{first.lower()}.{last.lower()}@campus.example",
                department=departments[dept - 1], title="Professor",
            )
            for index, (first, last, dept) in enumerate([
                ("Sarah", "Mitchell", 1), ("David", "Brooks", 2),
                ("Priya", "Sharma", 3), ("Daniel", "Reed", 4),
            ], 1)
        ]
        courses = [
            Course.objects.create(
                code=code, name=name, department=departments[dept - 1],
                faculty=faculty[dept - 1], credits=credits, capacity=capacity,
            )
            for code, name, dept, credits, capacity in [
                ("CS101", "Introduction to Computing", 1, 4, 40),
                ("CS202", "Data Structures", 1, 4, 35),
                ("BUS101", "Principles of Management", 2, 3, 50),
                ("ME201", "Engineering Mechanics", 3, 4, 30),
                ("ART110", "World Literature", 4, 3, 40),
            ]
        ]
        today = timezone.localdate()
        for index, (first, last, dept) in enumerate(people, 1):
            student = Student.objects.create(
                student_number=f"STU-{2026000 + index}", first_name=first, last_name=last,
                email=f"{first.lower()}.{last.lower()}@campus.example",
                department=departments[dept - 1], year=(index - 1) % 4 + 1, status="Active",
            )
            enrollment = Enrollment.objects.create(student=student, course=courses[{1: 0, 2: 2, 3: 3, 4: 4}[dept]], semester="Fall 2026", status="Enrolled")
            for day in range(5):
                status = "Absent" if (index + day) % 7 == 0 else ("Late" if (index + day) % 11 == 0 else "Present")
                Attendance.objects.create(enrollment=enrollment, date=today - timedelta(days=day), status=status)
            Fee.objects.create(
                student=student, description="Semester tuition", amount_cents=250000,
                paid_cents=250000 if index % 3 == 0 else 150000, due_date=today + timedelta(days=index - 5),
            )
        self.stdout.write(self.style.SUCCESS("Demo data added. No administrator account was created."))
