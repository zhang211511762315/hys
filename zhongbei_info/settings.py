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
    "agent_runtime",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "zhongbei_info.observability.CorrelationMiddleware",
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

CACHE_URL = os.getenv("CACHE_URL", "")
if CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "zhongbei-info",
        }
    }
PAGE_CACHE_SECONDS = int(os.getenv("PAGE_CACHE_SECONDS", "300"))
PAGE_CACHE_DETAIL_SECONDS = int(os.getenv("PAGE_CACHE_DETAIL_SECONDS", "600"))

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_IMPORTS = ("aggregator.tasks_wewe_rss",)
CELERY_BEAT_SCHEDULE = {}
CELERY_TASK_ROUTES = {
    "agent_runtime.tasks.execute_research_run_task": {"queue": "agent"},
    "agent_runtime.tasks.index_content_item_rag": {"queue": "agent"},
}
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TRACK_STARTED = True

WEWE_RSS_FEED_URL = os.getenv("WEWE_RSS_FEED_URL", "http://localhost:4000/feeds/all.atom")
WEWE_RSS_AUTH_CODE = os.getenv("WEWE_RSS_AUTH_CODE", "")
WEWE_RSS_SOURCE_NAME = os.getenv("WEWE_RSS_SOURCE_NAME", "微信公众号")

AI_PROVIDER = os.getenv("AI_PROVIDER", "rules")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_DAILY_BUDGET_CNY = os.getenv("DEEPSEEK_DAILY_BUDGET_CNY", "0.1")
DEEPSEEK_MONTHLY_BUDGET_CNY = os.getenv("DEEPSEEK_MONTHLY_BUDGET_CNY", "3")
DEEPSEEK_USD_TO_CNY = os.getenv("DEEPSEEK_USD_TO_CNY", "7.3")
DEEPSEEK_MAX_OUTPUT_TOKENS = int(os.getenv("DEEPSEEK_MAX_OUTPUT_TOKENS", "500"))
DEEPSEEK_INPUT_CACHE_HIT_USD_PER_MILLION = os.getenv("DEEPSEEK_INPUT_CACHE_HIT_USD_PER_MILLION", "0.0028")
DEEPSEEK_INPUT_CACHE_MISS_USD_PER_MILLION = os.getenv("DEEPSEEK_INPUT_CACHE_MISS_USD_PER_MILLION", "0.14")
DEEPSEEK_OUTPUT_USD_PER_MILLION = os.getenv("DEEPSEEK_OUTPUT_USD_PER_MILLION", "0.28")
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
MEILISEARCH_RAG_INDEX = os.getenv("MEILISEARCH_RAG_INDEX", "content_chunks")

RAG_MAX_CONTEXT_CHUNKS = int(os.getenv("RAG_MAX_CONTEXT_CHUNKS", "5"))
RAG_CHUNK_CHARS = int(os.getenv("RAG_CHUNK_CHARS", "900"))
RAG_CHUNK_OVERLAP_CHARS = int(os.getenv("RAG_CHUNK_OVERLAP_CHARS", "120"))
RAG_ANONYMOUS_DAILY_LIMIT = int(os.getenv("RAG_ANONYMOUS_DAILY_LIMIT", "5"))
RAG_MAX_OUTPUT_TOKENS = int(os.getenv("RAG_MAX_OUTPUT_TOKENS", "500"))
RAG_SEMANTIC_ENABLED = os.getenv("RAG_SEMANTIC_ENABLED", "0") == "1"
RAG_SEMANTIC_RATIO = float(os.getenv("RAG_SEMANTIC_RATIO", "0.35"))
RAG_EMBEDDER_NAME = os.getenv("RAG_EMBEDDER_NAME", "campus-multilingual-v1")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")
EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "15"))
RESEARCH_AGENT_DAILY_LIMIT = int(os.getenv("RESEARCH_AGENT_DAILY_LIMIT", str(RAG_ANONYMOUS_DAILY_LIMIT)))
RESEARCH_AGENT_CONCURRENT_LIMIT = int(os.getenv("RESEARCH_AGENT_CONCURRENT_LIMIT", "2"))
RESEARCH_AGENT_SESSION_MEMORY_ENABLED = os.getenv("RESEARCH_AGENT_SESSION_MEMORY_ENABLED", "0") == "1"
RESEARCH_AGENT_LLM_PLANNER_ENABLED = os.getenv("RESEARCH_AGENT_LLM_PLANNER_ENABLED", "0") == "1"
RESEARCH_AGENT_LLM_ANSWER_ENABLED = os.getenv("RESEARCH_AGENT_LLM_ANSWER_ENABLED", "0") == "1"
EVAL_PAID_ENABLED = os.getenv("EVAL_PAID_ENABLED", "0") == "1"
EVAL_PAID_HARD_CAP_CNY = int(os.getenv("EVAL_PAID_HARD_CAP_CNY", "5"))
RAG_SESSION_RETENTION_DAYS = int(os.getenv("RAG_SESSION_RETENTION_DAYS", "30"))
MEMORY_RETENTION_DAYS = int(os.getenv("MEMORY_RETENTION_DAYS", "180"))
SOURCE_FRESHNESS_HOURS = int(os.getenv("SOURCE_FRESHNESS_HOURS", "72"))
SOURCE_OPEN_FAILURE_THRESHOLD = int(os.getenv("SOURCE_OPEN_FAILURE_THRESHOLD", "5"))

SELF_HEAL_ENABLED = os.getenv("SELF_HEAL_ENABLED", "1") == "1"
SELF_HEAL_DAILY_ACTION_LIMIT = int(os.getenv("SELF_HEAL_DAILY_ACTION_LIMIT", "20"))
SELF_HEAL_STALE_JOB_MINUTES = int(os.getenv("SELF_HEAL_STALE_JOB_MINUTES", "120"))

MCP_ADMIN_TOKEN = os.getenv("MCP_ADMIN_TOKEN", "")
MCP_BIND_HOST = os.getenv("MCP_BIND_HOST", "127.0.0.1")

PUBLIC_SITE_BASE_URL = os.getenv("PUBLIC_SITE_BASE_URL", "http://127.0.0.1:8000")
PUBLIC_SITE_HTTPS = PUBLIC_SITE_BASE_URL.lower().startswith("https://")
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "1" if PUBLIC_SITE_HTTPS else "0") == "1"
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "1" if PUBLIC_SITE_HTTPS else "0") == "1"
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000" if PUBLIC_SITE_HTTPS else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
CRAWL_USER_AGENT = os.getenv("CRAWL_USER_AGENT", "ZhongbeiInfoBot/0.1 (+https://example.local)")
CRAWL_MAX_LINKS_PER_SOURCE = int(os.getenv("CRAWL_MAX_LINKS_PER_SOURCE", "50"))
CRAWL_DEFAULT_DEPTH = int(os.getenv("CRAWL_DEFAULT_DEPTH", "2"))
CRAWL_MAX_LIST_PAGES_PER_SOURCE = int(os.getenv("CRAWL_MAX_LIST_PAGES_PER_SOURCE", "8"))
CRAWL_RETRY_FAILED_URLS_PER_RUN = int(os.getenv("CRAWL_RETRY_FAILED_URLS_PER_RUN", "10"))
CRAWL_GROUP_PROBE_MIN_SOURCES = int(os.getenv("CRAWL_GROUP_PROBE_MIN_SOURCES", "3"))
CRAWL_GROUP_PROBE_SIZE = int(os.getenv("CRAWL_GROUP_PROBE_SIZE", "3"))
FETCH_TIMEOUT_SECONDS = float(os.getenv("FETCH_TIMEOUT_SECONDS", "12"))
FETCH_CONNECT_TIMEOUT_SECONDS = float(os.getenv("FETCH_CONNECT_TIMEOUT_SECONDS", "5"))
CRAWL_DIRECT_RETRY_ATTEMPTS = int(os.getenv("CRAWL_DIRECT_RETRY_ATTEMPTS", "2"))
CRAWL_FORCE_IPV4_DOMAINS = [part.strip().lower() for part in os.getenv("CRAWL_FORCE_IPV4_DOMAINS", ".nuc.edu.cn,nuc.edu.cn").split(",") if part.strip()]
CRAWL_DIRECT_FIRST = os.getenv("CRAWL_DIRECT_FIRST", "1") == "1"
CRAWL_BLOCK_PRIVATE_NETWORKS = os.getenv("CRAWL_BLOCK_PRIVATE_NETWORKS", "1") == "1"
CRAWL_RELAY_URL = os.getenv("CRAWL_RELAY_URL", "")
CRAWL_RELAY_TOKEN = os.getenv("CRAWL_RELAY_TOKEN", "")
CRAWL_RELAY_TIMEOUT_SECONDS = float(os.getenv("CRAWL_RELAY_TIMEOUT_SECONDS", "20"))
CRAWL_RELAY_ON_ERRORS = os.getenv("CRAWL_RELAY_ON_ERRORS", "connect,dns,network,timeout,5xx,429")
CRAWL_FAILURE_RETRY_BASE_MINUTES = int(os.getenv("CRAWL_FAILURE_RETRY_BASE_MINUTES", "30"))
CRAWL_FAILURE_RETRY_MAX_MINUTES = int(os.getenv("CRAWL_FAILURE_RETRY_MAX_MINUTES", "1440"))
CRAWL_NEAR_DUPLICATE_TEXT_THRESHOLD = float(os.getenv("CRAWL_NEAR_DUPLICATE_TEXT_THRESHOLD", "0.88"))
CRAWL_EMPLOYMENT_NOTICE_TYPE_IDS = [part.strip() for part in os.getenv("CRAWL_EMPLOYMENT_NOTICE_TYPE_IDS", "10831,9571544,9571539,10834,9571538,9571532").split(",") if part.strip()]
CRAWL_EMPLOYMENT_PAGE_SIZE = int(os.getenv("CRAWL_EMPLOYMENT_PAGE_SIZE", "15"))
CRAWL_SINCE_DATE = os.getenv("CRAWL_SINCE_DATE", "2026-01-01")
SCRAPY_MAX_PAGES_PER_SOURCE = int(os.getenv("SCRAPY_MAX_PAGES_PER_SOURCE", "5000"))
SCRAPY_MAX_DEPTH = int(os.getenv("SCRAPY_MAX_DEPTH", "6"))
