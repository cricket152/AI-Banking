# 源码审查包与部署素材

source-review.zip 是冻结代码提交 `9febd92`（分支 `feat/cards-scenarios`）的导出，包含源码、测试、evals、docs、README、项目配置与约束文件。不包含 .env、.local、数据库、凭据、虚拟环境、node_modules、浏览器会话或截图缓存。冻结版本不再含未提交工作树。

Windows / Python 3.12+（历史实测3.13.12）：
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c requirements-dev.lock
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m ai_banking.auth.cli create-user demo_user
.\.venv\Scripts\python.exe -m ai_banking
```
只在全新解压目录中复制示例配置；已有.env不能覆盖。账号密码由操作者设置，无默认账号。默认离线，不访问供应商；模型模式由服务端配置，密钥不能写入材料。第一次新库自动创建；旧库显式升级需先确认和备份，不能对既有运行库自动迁移。

核验：python -m pytest -q；python -m ruff check --no-cache src tests；python -m ruff format --no-cache --check src tests。
本轮素材制作不等于已做干净机器重装验收；已在全新 venv（Python 3.14.6，dev+observability）复测 232 项通过，最低 Python 3.12 与其他 OS 仍未实测。没有Docker/云部署完成声明，不启动公网服务。仓库参考：https://github.com/cricket152/AI-Banking 。
