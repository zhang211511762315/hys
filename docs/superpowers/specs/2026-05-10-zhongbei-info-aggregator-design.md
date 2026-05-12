# Zhongbei Info Aggregator Design

Build a Django-based public information aggregation site for Zhongbei University related content. The first version prioritizes reliable public-web crawling, manual social-link ingestion, text/image OCR, de-duplication, AI-assisted summary/category/tagging, source attribution, and public search.

The system uses Django for the public site and admin, MySQL for production data, Redis/Celery for scheduled jobs, Meilisearch for Chinese-friendly search, Tesseract for lightweight OCR on a 2-core/2GB server, and a pluggable AI provider layer for DeepSeek API or Ollama. Public pages show summaries and original links instead of republishing full articles.
