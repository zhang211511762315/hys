from .settings import *  # noqa: F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "zhongbei-info-tests",
    }
}

AI_PROVIDER = "rules"
DEEPSEEK_API_KEY = ""
MEILISEARCH_URL = ""
CRAWL_BLOCK_PRIVATE_NETWORKS = False
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Keep tests deterministic even when the checkout contains a production HTTPS
# environment file.  `settings.py` intentionally loads .env for local Docker
# workflows, so these test-only overrides must be explicit.
PUBLIC_SITE_BASE_URL = "http://testserver"
PUBLIC_SITE_HTTPS = False
SECURE_COOKIES = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
CSRF_TRUSTED_ORIGINS = []
