# AI-Banking

由两名开发者协作完成的 Agent 竞赛项目。本仓库用于管理需求、设计、代码、测试和竞赛交付材料。

项目基础设施已初始化，并形成[分步执行计划](docs/execution-plan.md)。第一版拟采用模拟银行、单 Agent 和三个业务场景，推荐 Python 后端；具体版本及关键契约待实施前确认。尚未实现 Agent、LLM 集成、工具调用、前端或部署能力。

## 开发成员

| 成员 | GitHub 账号 | 分工 |
| --- | --- | --- |
| 开发者 A | TODO: 待确认 | TODO: 待确认 |
| 开发者 B | TODO: 待确认 | TODO: 待确认 |

## 项目状态

- 已建立：项目文档、Git 协作约定、Issue / PR 模板及通用工程配置。
- 已规划：账单分析、订阅管理、智能转账及跨场景闭环；按任务逐步验收，不一次实现全部功能。
- 待完成：完整比赛规则核实、需求与架构文档固化、具体技术版本及授权参数确认。
- 当前没有应用入口、依赖清单、自动化测试或 CI；详细进度见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。
- 首次初始化提交已获批推送；后续文档和代码变更须按协作规范单独提交与审查。

## 目录结构

```text
.
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── pull_request_template.md
├── docs/
│   ├── architecture.md
│   ├── competition.md
│   ├── execution-plan.md
│   ├── requirements.md
│   └── roadmap.md
├── src/                     # 后续源代码，当前仅有 .gitkeep
├── tests/                   # 后续测试，当前仅有 .gitkeep
├── .editorconfig
├── .env.example
├── .gitattributes
├── .gitignore
├── AGENTS.md
├── CONTRIBUTING.md
├── PROJECT_STATUS.md
└── README.md
```

存在真实且可执行的检查任务后，再创建 `.github/workflows/`。

## 环境准备

1. 安装 Git，准备支持 UTF-8、LF 和 EditorConfig 的编辑器。
2. 配置本人的 Git 提交身份，并确认本人 GitHub 账号具有仓库协作权限。不要共用账号或凭据。
3. 阅读本文及 [协作规范](CONTRIBUTING.md)。开发语言、运行时版本和依赖安装方式将在技术选型确定后补充。
4. `.env.example` 当前仅包含说明，无已确定的配置变量。后续需要本地配置时，可复制为 `.env` 并按已确认的配置说明填写；真实密钥不得入库。

## 克隆方式

首次初始化推送完成后，另一位开发者执行：

```sh
git clone https://github.com/cricket152/AI-Banking.git
cd AI-Banking
git switch main
git pull --ff-only origin main
```

若远程仍为空，请先由维护者完成经批准的首次推送，再开始协作开发。

## 运行说明

当前没有可运行的业务程序、测试命令或部署命令。技术栈确定后，应在引入首个可运行功能时同步补充环境、安装、启动及验证说明，不使用占位脚本表示功能已实现。

## 协作方式

使用 Issue 明确目标和验收标准，从最新 `main` 创建独立分支，通过 PR 交由另一位开发者审查后合并。日常功能不直接提交到 `main`；优先使用 Squash Merge。详细步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)。

双方使用 Codex 时均应阅读 [AGENTS.md](AGENTS.md) 和 [PROJECT_STATUS.md](PROJECT_STATUS.md)，并以仓库中的实际代码、文档和 Git 状态为准。

## 文档索引

| 文档 | 用途 |
| --- | --- |
| [比赛要求](docs/competition.md) | 仓库内比赛要求的唯一权威记录；未核实规则统一标记待确认 |
| [项目需求](docs/requirements.md) | 目标、MVP、验收标准和待决问题 |
| [架构设计](docs/architecture.md) | 技术选型、模块、接口和部署决策 |
| [分步执行计划](docs/execution-plan.md) | 第一版任务、前置条件、验收关卡和长期目标；每次只执行一个任务 |
| [路线图](docs/roadmap.md) | 里程碑及完成条件 |
| [协作规范](CONTRIBUTING.md) | 分支、提交、PR 和验证流程 |
| [Codex 指令](AGENTS.md) | 项目级开发约束 |
| [项目状态](PROJECT_STATUS.md) | 已完成、未完成、问题与后续计划 |
