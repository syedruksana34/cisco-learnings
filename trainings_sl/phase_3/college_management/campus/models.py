import re

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


STUDENT_STATUSES = ("Active", "Graduated", "On leave")
ENROLLMENT_STATUSES = ("Enrolled", "Completed", "Dropped")
ATTENDANCE_STATUSES = ("Present", "Absent", "Late", "Excused")


def validate_phone_number(value):
    if not value:
        return
    if not re.fullmatch(r"[0-9]{10}", value):
        raise ValidationError("Contact number must contain exactly 10 digits (0-9), without spaces or country codes.")


class Department(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=200, unique=True)


class Person(models.Model):
    first_name = models.CharField(max_length=200)
    last_name = models.CharField(max_length=200)
    email = models.EmailField(max_length=200, unique=True)
    phone_number = models.CharField(max_length=32, blank=True, default="", validators=[validate_phone_number])
    department = models.ForeignKey(Department, on_delete=models.PROTECT)

    class Meta:
        abstract = True

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Student(Person):
    student_number = models.CharField(max_length=200, unique=True)
    year = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=[(value, value) for value in STUDENT_STATUSES])

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(year__gte=1, year__lte=8), name="student_year_range"),
            models.CheckConstraint(condition=Q(status__in=STUDENT_STATUSES), name="student_status_valid"),
        ]


class Faculty(Person):
    employee_number = models.CharField(max_length=200, unique=True)
    title = models.CharField(max_length=200)


class Course(models.Model):
    code = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, null=True, blank=True)
    credits = models.PositiveSmallIntegerField()
    capacity = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(credits__gte=1, credits__lte=12), name="course_credits_range"),
            models.CheckConstraint(condition=Q(capacity__gte=1, capacity__lte=1000), name="course_capacity_range"),
        ]


class Enrollment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    course = models.ForeignKey(Course, on_delete=models.PROTECT)
    semester = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=[(value, value) for value in ENROLLMENT_STATUSES])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["student", "course", "semester"], name="enrollment_unique"),
            models.CheckConstraint(condition=Q(status__in=ENROLLMENT_STATUSES), name="enrollment_status_valid"),
        ]
        indexes = [models.Index(fields=["course", "semester", "status"], name="enrollment_course_semester")]


class Attendance(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=[(value, value) for value in ATTENDANCE_STATUSES])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["enrollment", "date"], name="attendance_unique"),
            models.CheckConstraint(condition=Q(status__in=ATTENDANCE_STATUSES), name="attendance_status_valid"),
        ]


class Fee(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    description = models.CharField(max_length=200)
    amount_cents = models.PositiveIntegerField()
    paid_cents = models.PositiveIntegerField()
    due_date = models.DateField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gte=1, amount_cents__lte=2_147_483_647), name="fee_amount_range"),
            models.CheckConstraint(condition=Q(paid_cents__gte=0, paid_cents__lte=F("amount_cents")), name="fee_payment_range"),
        ]


class LoginAttempt(models.Model):
    username = models.CharField(max_length=80, unique=True)
    failures = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()


class KnowledgeDocument(models.Model):
    title = models.CharField(max_length=200)
    filename = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class KnowledgeChunk(models.Model):
    document = models.ForeignKey(KnowledgeDocument, related_name="chunks", on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    page = models.PositiveIntegerField(null=True, blank=True)
    text = models.TextField()

    class Meta:
        ordering = ["document_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["document", "position"], name="knowledge_chunk_position"),
        ]
