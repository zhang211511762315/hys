# Zhongbei Info Aggregator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable version of a Zhongbei University information aggregation website.

**Architecture:** Django serves the public site and admin. Celery workers run fetch/clean/OCR/AI/indexing jobs. MySQL is used in Docker production; SQLite is allowed for local tests.

**Tech Stack:** Django 5.2 LTS, MySQL 8.4, Redis, Celery, Meilisearch, Tesseract OCR, DeepSeek API, optional Ollama.

---

- [x] Add service tests for URL normalization, de-duplication, and AI classification.
- [x] Add Django page tests for published and unpublished content.
- [x] Scaffold Django project and aggregation app.
- [x] Implement models, admin actions, services, Celery tasks, public views, and templates.
- [x] Add Docker Compose and documentation.
- [x] Run migrations, tests, and Django checks.
