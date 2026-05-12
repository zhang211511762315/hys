from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_celery_beat",
    "aggregator",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "zhongbei_info.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "zhongbei_info.wsgi.application"
ASGI_APPLICATION = "zhongbei_info.asgi.application"

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite")
if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("MYSQL_DATABASE", "zhongbei_info"),
            "USER": os.getenv("MYSQL_USER", "zhongbei"),
            "PASSWORD": os.getenv("MYSQL_PASSWORD", "zhongbei"),
            "HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.getenv("MYSQL_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_BEAT_SCHEDULE = {}

AI_PROVIDER = os.getenv("AI_PROVIDER", "rules")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:0.6b")

OCR_PROVIDER = os.getenv("OCR_PROVIDER", "tesseract")
TESSERACT_LANG = os.getenv("TESSERACT_LANG", "chi_sim+eng")
OCR_MIN_TEXT_LENGTH = int(os.getenv("OCR_MIN_TEXT_LENGTH", "500"))
OCR_MAX_IMAGES_PER_PAGE = int(os.getenv("OCR_MAX_IMAGES_PER_PAGE", "3"))
OCR_ENABLE_FOR_WEB = os.getenv("OCR_ENABLE_FOR_WEB", "0") == "1"

MEILISEARCH_URL = os.getenv("MEILISEARCH_URL", "")
MEILISEARCH_MASTER_KEY = os.getenv("MEILISEARCH_MASTER_KEY", "")
MEILISEARCH_INDEX = os.getenv("MEILISEARCH_INDEX", "content_items")

PUBLIC_SITE_BASE_URL = os.getenv("PUBLIC_SITE_BASE_URL", "http://127.0.0.1:8000")
CRAWL_MAX_LINKS_PER_SOURCE = int(os.getenv("CRAWL_MAX_LINKS_PER_SOURCE", "50"))
CRAWL_DEFAULT_DEPTH = int(os.getenv("CRAWL_DEFAULT_DEPTH", "2"))
CRAWL_MAX_LIST_PAGES_PER_SOURCE = int(os.getenv("CRAWL_MAX_LIST_PAGES_PER_SOURCE", "8"))
FETCH_TIMEOUT_SECONDS = float(os.getenv("FETCH_TIMEOUT_SECONDS", "12"))
CRAWL_SINCE_DATE = os.getenv("CRAWL_SINCE_DATE", "2026-01-01")
SCRAPY_MAX_PAGES_PER_SOURCE = int(os.getenv("SCRAPY_MAX_PAGES_PER_SOURCE", "5000"))
SCRAPY_MAX_DEPTH = int(os.getenv("SCRAPY_MAX_DEPTH", "6"))
