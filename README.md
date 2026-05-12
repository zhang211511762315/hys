# 中北信息聚合网站

一个面向中北大学相关公开信息的聚合网站 MVP。系统支持后台维护信息源，抓取公开网页或手动添加的社媒/公众号具体链接，经过清洗、OCR、去重、AI 摘要/分类/标签后自动发布到公开页面。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_sources
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver
```

默认本地使用 SQLite 和规则分类，方便无 API Key 开发。后台地址是 `http://127.0.0.1:8000/admin/`。

## 云端 Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py seed_sources
docker compose exec web python manage.py createsuperuser
```

2核2G 服务器建议保留 `worker --concurrency=1`，并给系统配置 swap。`.env` 中设置 `DEEPSEEK_API_KEY` 后，`AI_PROVIDER=deepseek` 会调用 DeepSeek；没有 Key 时可以改成 `AI_PROVIDER=rules`。本地模型可用 `AI_PROVIDER=ollama`，但不建议在 2G 服务器上常驻大模型。

## 采集策略

- 官网、学院站和部门站作为自动信息源。
- 官网类来源默认 5 分钟检查一次；抖音、小红书、公众号等社媒链接默认每天检查一次。
- 抓取会从入口页继续发现通知/新闻列表页，再从列表页发现文章页。
- 对中北主站的 `/info/...htm`、就业网的 `/detail/news?id=...`、常见高校 `content.jsp?wbnewsid=...` 文章链接做识别。
- 内容按重要度分数排序，分数综合来源优先级、关键词、分类和原文发布时间；旧文章会降权。
- 抖音、小红书、公众号第一版只添加具体内容链接，不自动监控账号主页。
- 公开页面展示摘要、标签、来源、发布时间和原文链接，不转载全文。
- 社媒/公众号链接默认启用 OCR；官网类网页默认跳过 OCR 以保证抓取速度，可用 `OCR_ENABLE_FOR_WEB=1` 打开。

## 常用维护命令

```powershell
.\.venv\Scripts\python manage.py seed_sources
.\.venv\Scripts\python manage.py crawl_sources --all --limit 5 --max-articles 20
.\.venv\Scripts\python manage.py refresh_importance_scores
```
