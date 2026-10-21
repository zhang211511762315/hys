# HYS 项目入口

- Django 业务在 `aggregator` 和 `agent_runtime`；开发前读取 `.agents/skills/hys-development/SKILL.md`，当前操作见 `deploy/OPERATIONS.md`。
- 测试使用合成数据和模拟上游；设置不自动查找 `.env`，开发需要时显式指定 `HYS_ENV_FILE`。不要运行真实模型、生产抓取或第二个 scheduler 做验证。
- `PUBLIC_WORKSPACE_ENABLED=1` 是用户选择的公网免登录共享工作区，使用固定内部身份；保留旧归属和共享额度，不重新增加登录拦截。系统用户管理不公开。
- 三项目导航由 `aggregator/portal.py` 驱动；WeWe RSS 属于 HYS 来源管理，不新增独立一级 RSS 或抖音项目。
- 基础设施与应用 Compose 分开；发布先维护排空，回退只切应用，不恢复数据库或删除增量 schema。

当前交付：`/home/ubuntu/projects/codex-workspace/simplification-20261020/REPORT.md`。旧交付报告仅描述历史。
