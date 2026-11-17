import logging

from django.core.exceptions import RequestDataTooBig, SuspiciousOperation
from django.db import DatabaseError, IntegrityError
from django.db.models.deletion import ProtectedError
from django.http import Http404, JsonResponse

from .services import RecordValidationError


logger = logging.getLogger(__name__)


class APIErrorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.path.startswith("/api/"):
            if response.status_code >= 400 and not response.headers.get("Content-Type", "").startswith("application/json"):
                replacement = JsonResponse({"error": response.reason_phrase}, status=response.status_code)
                for header in ("Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"):
                    if header in response:
                        replacement[header] = response[header]
                response = replacement
            response.headers["Cache-Control"] = "no-store"
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, RecordValidationError):
            return JsonResponse({"error": str(exception)}, status=400)
        if isinstance(exception, Http404):
            return JsonResponse({"error": "Record or endpoint not found."}, status=404)
        if isinstance(exception, RequestDataTooBig):
            return JsonResponse({"error": "Request body exceeds the 64 KB limit."}, status=413)
        if isinstance(exception, ProtectedError):
            return JsonResponse({"error": "This record is linked to other records. Remove or reassign those records first."}, status=409)
        if isinstance(exception, IntegrityError):
            logger.warning("Database rejected a conflicting record: %s", exception)
            return JsonResponse({"error": "A record with these unique details already exists, or a linked record changed. Reload and check your values."}, status=409)
        if isinstance(exception, DatabaseError):
            logger.exception("MySQL operation failed")
            return JsonResponse({"error": "MySQL is unavailable or not initialized. Check server logs, database settings, and run migrations."}, status=503)
        if isinstance(exception, SuspiciousOperation):
            logger.warning("Invalid request: %s", exception)
            return JsonResponse({"error": "Invalid request."}, status=400)
        return None
