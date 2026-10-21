# AI-Banking

由两名开发者协作完成的 Agent 竞赛项目。当前按 [分步执行计划](docs/execution-plan.md) 推进 T00–T02：核实比赛范围、固定架构契约并建立最小 Python 工程检查。尚未实现银行业务、Agent、模型调用或用户界面。

## 当前范围

- 官方公开赛题要求至少覆盖六类金融场景中的三个；本项目计划选择账单分析、订阅管理和智能转账，并验证一个跨场景闭环。
- 比赛官方完整规则尚未核实，场景范围和授权参数仍待团队验收，详见 [比赛要求](docs/competition.md) 与 [项目需求](docs/requirements.md)。
- 当前没有真实银行、支付渠道、真实客户数据、外部模型或可运行的业务服务。

## 环境准备

要求 Python 3.12 或更新版本。依赖配置位于 `pyproject.toml`，目前只包含测试与静态检查工具。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

POSIX shell 激活命令：

```sh
source .venv/bin/activate
```

## 检查

```sh
python -m pytest
python -m ruff check --no-cache src tests
python -m ruff format --no-cache --check src tests
```

尚无应用启动命令；业务入口将在对应任务验收后补充。`.env.example` 不声明未经确认的模型或服务配置，真实密钥不得入库。

## 项目文档

- [比赛要求](docs/competition.md)：唯一权威的赛题和官方规则记录。
- [项目需求](docs/requirements.md)：计划范围、验收用例与待决问题。
- [架构设计](docs/architecture.md)：数据契约、身份与资金边界、系统模块。
- [分步执行计划](docs/execution-plan.md)：T00–T18 任务、依赖和验收关卡。
- [路线图](docs/roadmap.md)：阶段完成条件。
- [协作规范](CONTRIBUTING.md)：分支、提交、PR 与审查流程。
- [项目状态](PROJECT_STATUS.md)：已完成、待验收和后续任务。
