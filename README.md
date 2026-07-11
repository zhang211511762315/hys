# 中北信息聚合网站

一个面向中北大学相关公开信息的 Agent 化聚合网站。系统支持后台维护信息源，抓取公开网页或手动添加的社媒/公众号具体链接，经过清洗、OCR、去重、AI 摘要/分类/标签后自动发布到公开页面，并提供基于已发布内容的 RAG 问答助手。

## Agent / RAG 能力

- 采集 Agent：Celery 调度抓取任务，Agent runtime 记录抓取、抽取、去重、AI 分类、索引和自愈步骤。
- RAG 问答：`/ask/` 基于已发布公开内容回答问题，展示引用来源、本轮 token、本轮费用和会话累计费用。
- 成本控制：DeepSeek 默认日预算 `0.1 CNY`、月预算 `3 CNY`，超预算自动转为零成本检索式回答。
- 自动评测：`agent_eval --json` 固定问题集评估检索命中率、期望关键词命中率、引用覆盖和零成本评测结果，并记录到 Agent runtime。
- 低成本自愈：`agent_self_heal` 只执行确定性动作，如标记卡住任务、重试失败源、补建 RAG 索引，不调用 LLM、不写代码、不部署。
- 安全工具接口：`run_mcp_server` 暴露本地 MCP 工具，用于查询公开内容、站点健康和自愈 dry-run。

## 面试展示入口

- `/`：真实校园信息流，面向普通用户，展示系统不是静态作品页。
- `/agent/`：AI Agent 工程项目页，展示数据规模、工作流、运行记录、评测、成本控制和 MCP 工具边界。
- `/ask/`：RAG 问答演示页，可用示例问题验证引用溯源、流式回答、token/费用统计和 fallback。

简历建议写法见 `docs/resume/ai-agent-project.md`。推荐面试讲解顺序：业务问题 -> Agent 工作流 -> RAG 与引用 -> 成本控制 -> 自动评测与可观测 -> 上线约束。

## 技术栈

- Web：Django 5.2、Django Templates、Gunicorn ASGI、Uvicorn worker、Nginx。
- 数据与队列：MySQL 8.4、Redis 7、Celery、django-celery-beat。
- 搜索/RAG：Meilisearch、RAG chunk 索引、引用溯源。
- Agent/LLM：LangGraph、MCP Python SDK、LiteLLM、Pydantic、DeepSeek API。
- 内容处理：httpx、BeautifulSoup、trafilatura、Scrapy、Tesseract OCR、Pillow。

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
docker compose exec web python manage.py rebuild_rag_index
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
.\.venv\Scripts\python manage.py rebuild_rag_index
.\.venv\Scripts\python manage.py agent_eval
.\.venv\Scripts\python manage.py agent_eval --json
.\.venv\Scripts\python manage.py agent_self_heal --dry-run
```
