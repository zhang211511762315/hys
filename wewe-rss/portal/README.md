# HYS 公众号目录接入

固定 WeWe RSS 2.6.1 的原生界面和 tRPC，叠加 `/hys/rss/` 路径、HYS 返回导航及公开共享工作区的凭据屏蔽。登录凭据留在服务器，扫码流程使用短期服务端交接标识；保存已屏蔽的 token 不覆盖原值。

镜像：`schoolsearch-rss:20261103-audit`；上游基础镜像 digest 见 Dockerfile。构建：`docker build -t schoolsearch-rss:20261103-audit wewe-rss/portal`。运行必须启用 `--init`，Compose 已设 `init: true`，使正常停止信号转发至 Node。

本地运行环境文件 `wewe-rss/portal-container.env` 只由 root 读取，不进 Git；示例文件不含凭据。生产仍使用原数据目录，不在切换时运行 schema 迁移。

验收使用空 SQLite、内部网络及合成账号：15 项接入约束、13 个原生场景、凭据屏蔽与正常退出通过。真实扫码和抓取未执行。当前单独容器的排空与回退见服务器验收报告；此声明 Compose 文件不授权并行启动第二个生产实例。
