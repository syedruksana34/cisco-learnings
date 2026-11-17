import csv
import io
import logging
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.utils import timezone

from .assistant import reply
from . import rag
from .extraction import SUPPORTED_EXTENSIONS, ExtractionUnavailable
from .models import Attendance, Department, Fee, KnowledgeDocument, LoginAttempt
from .services import (
    RESOURCES, RecordValidationError, all_records, json_body, record_queryset,
    resource_config, save_record, serialize,
)


logger = logging.getLogger(__name__)


def endpoint(methods, public=False):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not public and not (request.user.is_authenticated and request.user.is_active and request.user.is_staff):
                return JsonResponse({"error": "Please sign in with an administrator account to continue."}, status=401)
            if request.method not in methods:
                response = JsonResponse({"error": "Method not allowed."}, status=405)
                response["Allow"] = ", ".join(methods)
                return response
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


@endpoint(["GET"], public=True)
def index(request):
    return render(request, "index.html", {
        "allow_signup": settings.ALLOW_OPEN_SIGNUP, "rag_enabled": settings.RAG_ENABLED,
        "knowledge_formats": ",".join(sorted(SUPPORTED_EXTENSIONS)),
    })


@endpoint(["GET"], public=True)
def session_info(request):
    user = request.user
    return JsonResponse({
        "user": {"username": user.username} if user.is_authenticated and user.is_active and user.is_staff else None,
        "csrf_token": get_token(request),
    })


@endpoint(["POST"], public=True)
def login(request):
    data = json_body(request)
    username, password = data.get("username", ""), data.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str) or not username.strip() or len(username) > 80 or len(password) > 256:
        raise RecordValidationError("Provide a valid username and password.")
    username = username.strip()
    now = timezone.now()
    with transaction.atomic():
        attempt, _ = LoginAttempt.objects.get_or_create(username=username, defaults={"window_start": now})
        attempt = LoginAttempt.objects.select_for_update().get(pk=attempt.pk)
        if attempt.window_start < now - timedelta(minutes=15):
            attempt.failures, attempt.window_start = 0, now
        if attempt.failures >= 10:
            return JsonResponse({"error": "Too many sign-in attempts. Try again in 15 minutes."}, status=429)
        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_staff:
            attempt.failures += 1
            attempt.save()
            return JsonResponse({"error": "Incorrect username or password."}, status=401)
        attempt.delete()
    auth_login(request, user)
    request.session.set_expiry(8 * 60 * 60)
    return JsonResponse({"user": {"username": user.username}, "csrf_token": get_token(request)})


@endpoint(["POST"])
def logout(request):
    auth_logout(request)
    rotate_token(request)
    return JsonResponse({"message": "Signed out."})


@endpoint(["POST"], public=True)
def signup(request):
    if not settings.ALLOW_OPEN_SIGNUP:
        return JsonResponse({"error": "Self-registration is disabled. Contact your administrator."}, status=403)
    if request.user.is_authenticated:
        return JsonResponse({"error": "Sign out before creating a new account."}, status=409)
    data = json_body(request)
    if set(data) != {"username", "password", "confirm_password"}:
        raise RecordValidationError("Provide username, password, and confirm_password only.")
    username, password, confirmation = data["username"], data["password"], data["confirm_password"]
    if not isinstance(username, str) or not username.strip() or len(username.strip()) > 80:
        raise RecordValidationError("Username must contain 1-80 characters.")
    if not isinstance(password, str) or not isinstance(confirmation, str) or len(password) > 256:
        raise RecordValidationError("Provide a password of 12-256 characters and confirmation.")
    if password != confirmation:
        raise RecordValidationError("Passwords do not match.")
    user = get_user_model()(username=username.strip(), is_staff=True, is_superuser=False)
    try:
        validate_password(password, user)
        user.full_clean(exclude=["password"])
    except ValidationError as exc:
        raise RecordValidationError(" ".join(exc.messages)) from exc
    with transaction.atomic():
        user.set_password(password)
        user.save()
    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(8 * 60 * 60)
    return JsonResponse({"user": {"username": user.username}, "csrf_token": get_token(request)}, status=201)


@endpoint(["POST"])
def chatbot(request):
    data = json_body(request)
    message = data.get("message")
    allowed = {"message", "history", "document_id"} if settings.RAG_ENABLED else {"message"}
    if set(data) - allowed or not isinstance(message, str) or not message.strip() or len(message) > 500:
        raise RecordValidationError("Send a message containing 1-500 characters, with optional history and document_id in RAG mode only.")
    if not settings.RAG_ENABLED:
        return JsonResponse(reply(message.strip()))
    history = rag.validate_history(data.get("history", []))
    try:
        return JsonResponse(rag.reply(message.strip(), history, data.get("document_id")))
    except rag.RAGUnavailable as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except rag.RAGGenerationError as exc:
        return JsonResponse({"error": str(exc)}, status=502)


def document_data(document):
    return {
        "id": document.pk, "title": document.title, "filename": document.filename,
        "created_at": document.created_at.isoformat(), "chunk_count": document.chunks.count(),
    }


@endpoint(["GET", "POST"])
def knowledge(request):
    if request.method == "GET":
        return JsonResponse({
            "data": [document_data(doc) for doc in KnowledgeDocument.objects.order_by("-pk").prefetch_related("chunks")],
            "mode": "rag" if settings.RAG_ENABLED else "local",
            "model": settings.OLLAMA_MODEL,
        })
    if request.content_type == "multipart/form-data":
        if set(request.POST) != {"title"} or set(request.FILES) != {"file"} or len(request.FILES.getlist("file")) != 1:
            raise RecordValidationError("Provide a title and exactly one supported file.")
        try:
            document = rag.save_document(request.POST["title"], upload=request.FILES["file"])
        except ExtractionUnavailable as exc:
            logger.warning("Local knowledge extraction dependency unavailable")
            return JsonResponse({"error": str(exc)}, status=503)
    else:
        data = json_body(request)
        if set(data) != {"title", "text"}:
            raise RecordValidationError("Provide title and text only.")
        document = rag.save_document(data["title"], text=data["text"])
    return JsonResponse({"data": document_data(document)}, status=201)


@endpoint(["GET", "DELETE"])
def knowledge_detail(request, document_id):
    document = KnowledgeDocument.objects.filter(pk=document_id).first()
    if document is None:
        raise Http404
    if request.method == "DELETE":
        document.delete()
        return HttpResponse(status=204)
    return JsonResponse({"data": {
        **document_data(document),
        "chunks": list(document.chunks.values("position", "page", "text")),
    }})


@endpoint(["GET"])
def dashboard(request):
    counts = {name: model.objects.count() for name, (model, _) in RESOURCES.items()}
    finance = Fee.objects.aggregate(total_cents=Sum("amount_cents", default=0), paid_cents=Sum("paid_cents", default=0))
    attendance = Attendance.objects.aggregate(total=Count("pk"), attended=Count("pk", filter=Q(status__in=("Present", "Late"))))
    departments = list(Department.objects.annotate(count=Count("student")).order_by("-count", "name").values("name", "count"))
    recent_students = [serialize("students", row) for row in record_queryset("students")[:5]]
    outstanding = record_queryset("fees").filter(paid_cents__lt=F("amount_cents")).order_by("due_date", "pk")[:5]
    return JsonResponse({
        "counts": counts, "finance": finance, "attendance": attendance, "departments": departments,
        "recent_students": recent_students,
        "outstanding_fees": [serialize("fees", row) for row in outstanding],
    })


@endpoint(["GET", "POST"])
def collection(request, resource):
    resource_config(resource)
    if request.method == "POST":
        obj = save_record(resource, json_body(request))
        return JsonResponse({"data": serialize(resource, obj, display=False)}, status=201)
    records = all_records(resource)
    query = request.GET.get("q", "").strip().casefold()
    if query:
        records = [row for row in records if any(query in str(value).casefold() for value in row.values())]
    for key in ("department_id", "student_id", "course_id", "enrollment_id", "status", "semester", "date"):
        if key in request.GET:
            records = [row for row in records if str(row.get(key)) == request.GET[key]]
    return JsonResponse({"data": records, "total": len(records)})


@endpoint(["GET", "PUT", "DELETE"])
def detail(request, resource, record_id):
    model, _ = resource_config(resource)
    if request.method == "PUT":
        if not model.objects.filter(pk=record_id).exists():
            raise Http404
        obj = save_record(resource, json_body(request), record_id)
        return JsonResponse({"data": serialize(resource, obj, display=False)})
    if request.method == "DELETE":
        with transaction.atomic():
            obj = model.objects.select_for_update().filter(pk=record_id).first()
            if obj is None:
                raise Http404
            obj.delete()
        return HttpResponse(status=204)
    obj = record_queryset(resource).filter(pk=record_id).first()
    if obj is None:
        raise Http404
    return JsonResponse({"data": serialize(resource, obj)})


@endpoint(["GET"])
def export_resource(request, resource):
    _, editable = resource_config(resource)
    records = all_records(resource)
    output = io.StringIO(newline="")
    fields = list(records[0]) if records else ["id", *editable]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in records:
        writer.writerow({
            key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value
            for key, value in row.items()
        })
    response = HttpResponse(output.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{resource}.csv"'
    return response


def csrf_failure(request, reason=""):
    logger.warning("CSRF rejected a request: %s", reason)
    return JsonResponse({"error": "Your session expired or the CSRF token is invalid. Reload the page and try again."}, status=403)


def bad_request(request, exception):
    return JsonResponse({"error": "Invalid request."}, status=400)


def permission_denied(request, exception):
    return JsonResponse({"error": "Permission denied."}, status=403)


def not_found(request, exception):
    return JsonResponse({"error": "Record or endpoint not found."}, status=404)


def server_error(request):
    return JsonResponse({"error": "An unexpected server error occurred. Check the server logs."}, status=500)
