# AI-Banking

由两名开发者协作完成的 Agent 竞赛项目。已建立可运行的本地模拟环境：安全登录、独立账户与流水、查询及意图准备 Agent、Web 工作台。默认是明确标注的离线演示，可通过服务端配置接入真实工具调用模型。所有资金和用户数据均为虚构。

## 当前范围

- 官方公开赛题要求至少覆盖六类金融场景中的三个；本项目计划选择账单分析、订阅管理和智能转账，并验证一个跨场景闭环。
- 比赛官方完整规则尚未核实，场景范围仍待团队验收，详见 [比赛要求](docs/competition.md) 与 [项目需求](docs/requirements.md)。
- 已实现模拟转账、订阅取消、人工确认和预授权管理 UI。Agent 支持查询、澄清、逐笔确认后续办，以及用户在当前对话显式选定预授权后的受控自动执行；重复请求复用原操作，超限或结果未知时暂停。三场景组合任务已用模拟模型和真实银行执行器验证，新闭环的真实模型验收与队友审查仍待完成。没有真实银行、支付渠道或真实客户数据。
- 理财操作与卡片管理目前只有模拟只读查询（产品目录、风险等级、脱敏卡信息），不支持申购、赎回、申请、调额、冻结或挂失；如实现写操作需独立授权与验收。

## 环境准备

要求 Python 3.12 或更新版本。后端使用 FastAPI、Pydantic、SQLite；前端采用同源原生 HTML / CSS / JavaScript，无需 Node 构建。依赖配置位于 `pyproject.toml`。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]" -c requirements-dev.lock
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

## 启动工作台

在根目录激活环境后执行（已有 `.env` 时保留原配置）：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m ai_banking.auth.cli create-user alice
python -m ai_banking
```

按终端提示设置 1–128 字符的密码，本地测试可使用短密码。打开 [本地工作台](http://127.0.0.1:8000) 登录。没有默认密码。详见 [本地运行与模型接入](docs/local-development.md)；真实 API Key 仅放已忽略的 `.env`。

终端默认显示用户输入、供应商返回的可见思考 / 摘要、工具调用与结果、助手回复。旧数据库启用新增银行服务前须确认并备份升级，步骤及 API 见 [模拟银行业务契约](docs/banking-services.md)；启动不会自动改造已有数据库。

可选接入 LangSmith 查看树形轨迹、模型消息、工具结果与 usage。默认关闭，不改变 Agent 编排；安装可选依赖、创建 Key、配置 `.env` 并运行连接自检的步骤见 [LangSmith 接入](docs/langsmith.md)。

## 目录与协作

`src/ai_banking/` 包含认证、数据服务、Agent 适配和 Web 页面，`tests/` 保存环境与安全集成测试，`docs/` 维护设计与计划，`.github/` 提供协作模板。两位成员的账号与职责仍待确认；日常开发使用独立分支及 PR，由另一位审查后优先 Squash Merge。

## 项目文档

- [比赛要求](docs/competition.md)：唯一权威的赛题和官方规则记录。
- [项目需求](docs/requirements.md)：计划范围、验收用例与待决问题。
- [架构设计](docs/architecture.md)：数据契约、身份与资金边界、系统模块。
- [认证契约](docs/authentication.md)：T01-A 身份认证、会话生命周期及 T03 验收用例。
- [模拟银行业务](docs/banking-services.md)：记账、恢复、审批、预授权、报表、订阅和升级说明。
- [Agent 受控操作](docs/agent-operations.md)：页面使用步骤、人工确认、预授权、多步骤续办与恢复边界。
- [Agent 提示词评测](docs/agent-evaluation.md)：36 条测试用例、真实模型评测命令、工具及执行断言和语义复核边界。
- [本地开发](docs/local-development.md)：安装、登录、模型配置、运行限制和验收方法。
- [LangSmith 接入](docs/langsmith.md)：API Key、可选安装、连接自检、可视化追踪与隐私边界。
- [分步执行计划](docs/execution-plan.md)：T00–T18 任务、依赖和验收关卡。
- [路线图](docs/roadmap.md)：阶段完成条件。
- [协作规范](CONTRIBUTING.md)：分支、提交、PR 与审查流程。
- [项目状态](PROJECT_STATUS.md)：已完成、待验收和后续任务。
