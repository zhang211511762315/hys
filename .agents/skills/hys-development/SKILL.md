---
name: hys-development
description: Develop, test and deploy the HYS Django application, research workers and source ingestion on this server.
---

# HYS 开发与验证

项目 `/home/ubuntu/hys`：`aggregator` 负责信息、抓取和搜索，`agent_runtime` 负责问答与研究。
当前运行与操作入口见 `deploy/OPERATIONS.md`；历史优化报告是发布记录，不是可重跑的安装器。

## 验证

`requirements-dev.txt` 提供 pytest；`zhongbei_info.settings_test` 使用内存 SQLite、本地缓存和规则模型。
设置不会自动查找 `.env`；本地开发需要时显式设置 `HYS_ENV_FILE`。合成数据和模拟上游用于测试，
不读取用户内容，不调用真实收费模型或提交生产抓取。MySQL 专项需要独立测试库。

修改后先执行相应行为回归；配置或依赖变更再执行全套必要检查。Ruff 不自动修复，
ShellCheck 只做静态检查。测试通过与线上已更新分别报告。

## 行为与部署

公开模式通过固定内部身份共享业务数据和额度，系统用户管理保持关闭。关闭公开模式后，
研究 API 恢复未登录 401、跨用户 404。创建与重放共用额度、并发和幂等校验。

基础设施和应用 Compose 分开；迁移、静态准备、启动分别操作。研究队列为 `agent,agent_v2`，
普通队列为 `celery`，scheduler 始终一个。单实例维护发布先阻止新写入、等待已有任务完成；
不强杀、不覆盖生产数据库、不为普通代码回退删除增量 schema。
