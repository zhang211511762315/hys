# HYS 当前运维入口

基础设施：`docker compose -p hys -f docker-compose.yml`，管理 MySQL、Redis、Meilisearch、Nginx 和证书。
应用：`docker compose -p hys-release -f docker-compose.release.yml`，管理 Web、普通 worker、研究 worker、唯一 scheduler。
不要在应用发布时执行基础设施 `up`、`down` 或删除卷。应用发布使用 `sudo deploy/scripts/release.sh --maintenance [镜像标签]`。

镜像由项目 Dockerfile 从固定 Python 基础镜像、requirements 与 constraints 直接构建，运行时不带 pytest。
开发环境安装 `requirements-dev.txt`；测试 `HYS_ENV_FILE= .venv/bin/python -m pytest -q`。
配置默认只读取进程环境；如需开发 `.env`，显式设置 `HYS_ENV_FILE=/path/to/.env`。生产由 Compose env_file 注入。

发布前完成隔离回归、备份和必要的独立静态准备。release.sh 将 HYS 新请求置为 503，正常停止应用、启动新版本，再恢复入口；
RP/Mobile 入口不受 HYS 维护影响。排空时间由现有任务决定，不强杀来满足发布时间。
首次接管前的旧命名容器由本次交接脚本处理，之后只使用上述应用 Compose。
发布失败会保留维护入口及原代理配置路径；应检查服务状态并从输出路径恢复代理配置，再重跑或按本次 ROLLBACK.md 恢复上一稳定版。

备份由 hys-backup.timer 调用 deploy/scripts/backup_mysql.sh，保持事务快照、校验与 7 天保留策略。
证书续期由 hys-certbot-renew.timer 管理，成功后重载容器和宿主 Nginx；不再单独每日重载。
当前共享工作区、目录挂载和旧入口均保留。数据库迁移和 collectstatic 不在启动命令中自动运行。

2026-10-20 精简交付、回退和证据：`/home/ubuntu/projects/codex-workspace/simplification-20261020/`。
