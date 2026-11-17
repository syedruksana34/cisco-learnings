import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    secret_path = INSTANCE_DIR / ".secret"
    try:
        with open(secret_path, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    SECRET_KEY = secret_path.read_text().strip()
    if not SECRET_KEY:
        raise ImproperlyConfigured("The session secret file is empty. Set SECRET_KEY.")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOW_OPEN_SIGNUP = os.environ.get("ALLOW_OPEN_SIGNUP", "1" if DEBUG else "0") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,[::1]").split(",") if host.strip()]
ROOT_URLCONF = "campusflow.urls"
WSGI_APPLICATION = "campusflow.wsgi.application"
ASGI_APPLICATION = "campusflow.asgi.application"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "campus",
]
MIDDLEWARE = [
    "campus.middleware.APIErrorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
    ]},
}]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE", "campusflow"),
        "USER": os.environ.get("MYSQL_USER", ""),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
        "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            "isolation_level": "read committed",
            **({"unix_socket": os.environ["MYSQL_UNIX_SOCKET"]} if os.environ.get("MYSQL_UNIX_SOCKET") else {}),
        },
        "TEST": {
            "NAME": os.environ.get("MYSQL_TEST_DATABASE", "test_campusflow"),
            "CHARSET": "utf8mb4",
            "COLLATION": "utf8mb4_bin",
        },
    }
}
if DATABASES["default"]["NAME"] == DATABASES["default"]["TEST"]["NAME"]:
    raise ImproperlyConfigured("MYSQL_TEST_DATABASE must differ from MYSQL_DATABASE to protect application data.")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
APPEND_SLASH = False
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_HTTPONLY = True
CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"
CSRF_FAILURE_VIEW = "campus.views.csrf_failure"
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 1
RAG_ENABLED = os.environ.get("RAG_ENABLED", "1") == "1"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = 90
WHISPER_MODEL_PATH = Path(os.environ.get(
    "WHISPER_MODEL_PATH", str(Path.home() / ".local/share/campusflow-whisper/tiny")
)).expanduser()
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
