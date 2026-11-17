import json
from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.utils import timezone

from .models import (
    ATTENDANCE_STATUSES, ENROLLMENT_STATUSES, STUDENT_STATUSES,
    Attendance, Course, Department, Enrollment, Faculty, Fee, Student, validate_phone_number,
)


RESOURCES = {
    "departments": (Department, ("name", "code")),
    "students": (Student, ("student_number", "first_name", "last_name", "email", "phone_number", "department_id", "year", "status")),
    "faculty": (Faculty, ("employee_number", "first_name", "last_name", "email", "phone_number", "department_id", "title")),
    "courses": (Course, ("code", "name", "department_id", "faculty_id", "credits", "capacity")),
    "enrollments": (Enrollment, ("student_id", "course_id", "semester", "status")),
    "attendance": (Attendance, ("enrollment_id", "date", "status")),
    "fees": (Fee, ("student_id", "description", "amount_cents", "paid_cents", "due_date")),
}


class RecordValidationError(ValueError):
    pass


def resource_config(resource):
    if resource not in RESOURCES:
        raise Http404
    return RESOURCES[resource]


def json_body(request):
    if request.content_type != "application/json":
        raise RecordValidationError("Request body must be a JSON object with Content-Type: application/json.")
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RecordValidationError("Request body must be valid JSON.") from exc
    if not isinstance(data, dict):
        raise RecordValidationError("Request body must be a JSON object.")
    return data


def integer(value, label, minimum=1, maximum=2_147_483_647):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RecordValidationError(f"{label} must be an integer between {minimum} and {maximum}.")
    return value


def validate_fields(resource, data):
    _, fields = resource_config(resource)
    unknown = set(data) - set(fields)
    missing = set(fields) - set(data)
    missing.discard("phone_number")
    if unknown:
        raise RecordValidationError(f"Unknown fields: {', '.join(sorted(unknown))}.")
    if missing:
        raise RecordValidationError(f"Required fields: {', '.join(sorted(missing))}.")
    values = {}
    numeric = {"year", "credits", "capacity", "amount_cents", "paid_cents"}
    limits = {"year": (1, 8), "credits": (1, 12), "capacity": (1, 1000), "paid_cents": (0, 2_147_483_647)}
    for field in fields:
        if field == "phone_number":
            if field not in data:
                continue
            value = data[field]
            if not isinstance(value, str):
                raise RecordValidationError("Contact number must be text, or an empty string to leave it blank.")
            value = value.strip()
            try:
                validate_phone_number(value)
            except DjangoValidationError as exc:
                raise RecordValidationError(" ".join(exc.messages)) from exc
            values[field] = value
            continue
        value = data[field]
        if field == "faculty_id" and value is None:
            values[field] = None
        elif field.endswith("_id") or field in numeric:
            values[field] = integer(value, field.replace("_", " "), *limits.get(field, (1, 2_147_483_647)))
        else:
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
                raise RecordValidationError(f"{field.replace('_', ' ')} is required and must be at most 200 characters.")
            values[field] = value.strip()
    if "email" in values:
        values["email"] = values["email"].lower()
        try:
            validate_email(values["email"])
        except DjangoValidationError as exc:
            raise RecordValidationError("Enter a valid email address.") from exc
    choices = {"students": STUDENT_STATUSES, "enrollments": ENROLLMENT_STATUSES, "attendance": ATTENDANCE_STATUSES}
    if resource in choices and values["status"] not in choices[resource]:
        raise RecordValidationError(f"Status must be one of: {', '.join(choices[resource])}.")
    for field in ("date", "due_date"):
        if field not in values:
            continue
        try:
            parsed = date.fromisoformat(values[field])
        except ValueError as exc:
            raise RecordValidationError("Dates must use YYYY-MM-DD format.") from exc
        if parsed.isoformat() != values[field]:
            raise RecordValidationError("Dates must use YYYY-MM-DD format.")
        if field == "date" and parsed > timezone.localdate():
            raise RecordValidationError("Attendance cannot be recorded for a future date.")
        values[field] = parsed
    return values


def validate_relationships(resource, values, original=None):
    references = {
        "department_id": Department, "faculty_id": Faculty,
        "student_id": Student, "course_id": Course, "enrollment_id": Enrollment,
    }
    related = {}
    # Lock parents before validating dependent writes so MySQL serializes capacity
    # checks and attendance/history edits with mutations of the parent record.
    for field in ("course_id", "student_id", "enrollment_id", "department_id", "faculty_id"):
        if values.get(field) is None:
            continue
        obj = references[field].objects.select_for_update().filter(pk=values[field]).first()
        if obj is None:
            raise RecordValidationError(f"The selected {field.removesuffix('_id')} does not exist.")
        related[field] = obj
    if resource == "fees" and values["paid_cents"] > values["amount_cents"]:
        raise RecordValidationError("Paid amount cannot exceed the total fee.")
    if resource == "enrollments":
        if values["status"] == "Enrolled":
            if related["student_id"].status != "Active":
                raise RecordValidationError("Only active students may enroll in a course.")
            count = Enrollment.objects.filter(course_id=values["course_id"], semester=values["semester"], status="Enrolled")
            if original:
                count = count.exclude(pk=original.pk)
            if count.count() >= related["course_id"].capacity:
                raise RecordValidationError("This course is at capacity for the selected semester.")
        if original and original.attendance_set.exists():
            if any(values[key] != getattr(original, key) for key in ("student_id", "course_id", "semester")):
                raise RecordValidationError("An enrollment with attendance cannot change student, course, or semester. Remove its attendance first.")
    if resource == "courses" and original:
        largest = Enrollment.objects.filter(course=original, status="Enrolled").values("semester").annotate(n=Count("pk")).order_by("-n").first()
        if largest and values["capacity"] < largest["n"]:
            raise RecordValidationError("Capacity cannot be lower than the current enrollment in any semester.")
    if resource == "attendance" and related["enrollment_id"].status == "Dropped":
        raise RecordValidationError("Attendance cannot be recorded for a dropped enrollment.")


@transaction.atomic
def save_record(resource, data, record_id=None):
    model, _ = resource_config(resource)
    values = validate_fields(resource, data)
    # Enrollment requests always lock their target course before their own row.
    if resource == "enrollments":
        list(Course.objects.select_for_update().filter(pk=values["course_id"]))
        list(Student.objects.select_for_update().filter(pk=values["student_id"]))
    original = None
    if record_id is not None:
        original = model.objects.select_for_update().filter(pk=record_id).first()
        if original is None:
            raise Http404
    validate_relationships(resource, values, original)
    if original is None:
        return model.objects.create(**values)
    for key, value in values.items():
        setattr(original, key, value)
    original.save()
    return original


def record_queryset(resource):
    model, _ = resource_config(resource)
    queryset = model.objects.order_by("-pk")
    if resource == "departments":
        return queryset.annotate(student_count=Count("student", distinct=True), course_count=Count("course", distinct=True))
    relations = {
        "students": ("department",), "faculty": ("department",),
        "courses": ("department", "faculty"), "enrollments": ("student", "course"),
        "attendance": ("enrollment__student", "enrollment__course"),
        "fees": ("student",),
    }
    return queryset.select_related(*relations[resource])


def serialize(resource, obj, display=True):
    _, fields = resource_config(resource)
    result = {"id": obj.pk}
    for key in fields:
        value = getattr(obj, key)
        result[key] = value.isoformat() if isinstance(value, date) else value
    if not display:
        return result
    if resource == "departments":
        result.update(student_count=obj.student_count, course_count=obj.course_count)
    elif resource in ("students", "faculty"):
        result["department"] = obj.department.name
    elif resource == "courses":
        result.update(department=obj.department.name, instructor=obj.faculty.full_name if obj.faculty else "Unassigned")
    elif resource == "enrollments":
        result.update(student=obj.student.full_name, student_number=obj.student.student_number, course=f"{obj.course.code} \u00b7 {obj.course.name}")
    elif resource == "attendance":
        result.update(student=obj.enrollment.student.full_name, course=obj.enrollment.course.code, semester=obj.enrollment.semester)
    elif resource == "fees":
        result.update(student=obj.student.full_name, student_number=obj.student.student_number, balance_cents=obj.amount_cents - obj.paid_cents)
    return result


def all_records(resource):
    return [serialize(resource, obj) for obj in record_queryset(resource)]
