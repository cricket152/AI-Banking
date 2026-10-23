# 本地运行与验收

当前交付包含本地登录、独立账户与流水、只读 Agent、终端运行轨迹、Web 工作台，以及模拟银行转账、恢复、授权、账单与订阅后端。新增资金 API 对应 T05–T11，尚无 Agent 写操作或前端审批表单；不代表 T14–T18 已完成。业务契约和旧数据库升级步骤见 [模拟银行业务](banking-services.md)。

## 1. 安装与启动

要求 Python 3.12+；本机实测版本和检查结果见 `PROJECT_STATUS.md`。无需 Node、前端构建工具、外部数据库或 Agent 框架。`requirements-dev.lock` 记录本次已验证的直接和传递依赖，安装时通过 pip 的约束选项使用；升级依赖后应重新验证并更新，不引入额外包管理器。

在项目根目录使用 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]" -c requirements-dev.lock
# 已存在 .env 时保留原文件，只补充所需配置。
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m ai_banking.auth.cli create-user alice
python -m ai_banking
```

创建用户会通过终端隐藏输入并确认密码（15–128 个字符），同时在一个事务内生成两个独立虚构账户和七条流水。没有固定默认账号或密码。用户名可替换为 3–32 位字母、数字或下划线，以字母开头；首尾空白移除并统一小写。

打开 [本地工作台](http://127.0.0.1:8000)。必须使用与 `BANK_ORIGIN` 完全相同的域名和端口；`localhost` 与 `127.0.0.1` 不能混用。修改端口时修改 `BANK_ORIGIN` 后重启即可。按 `Ctrl+C` 停止服务。

POSIX 环境用 `source .venv/bin/activate` 激活，使用 `test -f .env || cp .env.example .env` 创建配置，其余 Python 命令相同。勿覆盖已有配置。

命令均从仓库根目录运行，数据库相对路径也以当前工作目录为准。前端静态文件随 Python 包分发，FastAPI 同源提供页面与 API。

## 2. 可体验的功能

- 模拟登录、退出、刷新恢复 Cookie 会话；首次没有用户时显示本地创建指引。
- 总资产、两个账户、最近流水；账户筛选、金额显示 / 隐藏、刷新数据。
- 财务概览、账户、流水和独立助手页面；适配手机宽度、键盘操作、输入法与减少动效偏好。
- 对话记录写入 SQLite；刷新恢复最近对话，可创建新对话；只保存完整成功回合和失败状态，不自动重试。
- 离线模式可问“我的账户余额”“最近流水”“订阅支出”；回复由本地规则查询数据库生成，页面明确标注其不是 LLM。
- 升级后的状态包含事件版本、服务端时间、账户数量、授权、累计支出、预占和操作状态；Agent 权限仍是只读。旧库未升级时返回原只读快照，不虚构授权。

每位用户使用独立记录。初始样本金数相同不代表共享账户；ID 与归属不同，期初金额加流水净额与当前余额一致。新用户初始总资产为 ¥49,664.50，全部是虚构资金。收入 / 支出卡片仅合计当前最近流水，不能当作完整月报。

后端已提供受控转账、人工审批、显式预授权、账单统计与订阅取消 API；前端仍为查询工作台。尚无资金操作表单、Agent 写工具、定时任务、RAG、长期记忆或多 Agent。新数据库自动初始化；旧库须经明确确认运行 `python -m ai_banking.banking.cli upgrade`，启动不会自动升级。

## 3. 接入真实模型

默认 `AGENT_MODE=offline` 不访问模型。要使用 LLM，编辑本机 `.env`：

```dotenv
AGENT_MODE=model
MODEL_BASE_URL=https://api.openai.com/v1
MODEL_API=responses
MODEL_NAME=填写供应商实际支持的工具调用模型
MODEL_API_KEY=填写你自己的密钥
```

这里是配置说明，不能将示例中文占位当作真实参数。兼容 Chat Completions 的供应商可设置 `MODEL_API=chat`，端点为 `<MODEL_BASE_URL>/chat/completions`；Responses 端点为 `<MODEL_BASE_URL>/responses`。模型必须支持函数工具和相应 JSON Schema。默认不指定供应商模型型号，避免假定账号权限、费用或竞赛限制。

重启后页面显示“模型模式”及配置型号。真实连接是否可用须用自己的服务端密钥验证；本地自动化测试只用模拟 HTTP 响应验证两种协议，不证明真实模型已经联通。供应商错误返回明确失败，不静默切换到离线答案，也不自动重试。

模型模式会将提问、最近完整对话回合以及查询到的当前用户模拟财务数据发送到配置的 HTTPS 供应商。密码、认证 Cookie、CSRF、内部会话 ID 不进入消息和工具参数。应用传入 `store=false`，供应商的数据保留行为仍需按其规则核实。

固定顺序直接暴露五个只读工具：`list_accounts`、`get_transactions`、`list_payees`、`list_subscriptions`、`get_billing_summary`。新增业务工具需要银行表就绪。账单工具要求明确的起止日期。身份由服务端绑定，拒绝额外参数和未知工具；执行前重新验证会话。工具结果使用转义 XML 标记，不能授予权限或执行资金操作。模型文字不作为金额事实，财务面板始终读取数据库。

系统提示和工具定义固定，动态状态作为后续消息追加。上下文当前保留最多 12 个完整成功回合并按 20 KB 历史预算裁剪；每轮请求设 48 KB 序列化消息上限、默认 1500 输出 token 上限、最多四轮模型请求、每次最多四个工具调用，并设整轮 90 秒截止时间。`MODEL_MAX_OUTPUT_TOKENS` 可在 256–16384 间显式设置，供应商可能另有限制；思考模型的输出预算也可能用于推理，需结合轨迹中的 usage / incomplete 调整。字节预算不是精确 tokenizer 或所有模型的上下文保证。银行已有确定性任务检查点，但尚无 T15 的历史摘要、精确 token 管理及 Agent 写任务恢复；超限明确失败，不重放资金操作。

### 终端运行轨迹

通过 `python -m ai_banking` 启动，默认按请求 ID 输出时间和独立事件：用户输入、模型请求、模型可见思考 / 摘要、模型响应、工具调用、工具结果、助手回复、错误及重复请求回执。模型响应包含耗时和供应商返回的 usage；没有编造供应商未返回的统计。

Chat Completions 记录供应商返回的 `reasoning_content`，Responses 只记录公开 `summary_text` / `reasoning_text`；不解密或输出 `encrypted_content`，未提供时明确标注。离线模式没有模型思考，日志会说明是规则演示。当前为整轮响应后的阶段日志，不是逐 token 流式显示。

`.env` 中可设置：

```dotenv
AGENT_TRACE_ENABLED=true
AGENT_TRACE_CONTENT=true
```

`AGENT_TRACE_CONTENT=false` 保留阶段、耗时等元数据，隐藏输入、回复、思考和工具内容；`AGENT_TRACE_ENABLED=false` 关闭自定义轨迹。修改后重启生效，已有系统环境变量仍优先于 `.env`。

另可选安装 LangSmith SDK，将脱敏的整轮、模型与工具轨迹上传到指定 workspace 查看。终端开关与云端开关独立，默认 `LANGSMITH_TRACING=false`。创建 Key、配置、独立连接自检及排错见 [LangSmith 接入](langsmith.md)。没有引入 LangGraph 或改变模型请求；SDK / 上传故障不触发业务重试，关闭内容上传仍可记录实际 usage。

日志会脱敏已知密钥、凭据字段和常见敏感模式，转义控制字符并截断长内容；这不能识别任意未标记的个人秘密。只使用合成测试数据，不分享未经检查的终端输出。不会打印认证请求、原始供应商 HTTP 响应或异常响应体。

## 4. 认证与运行边界

- 密码通过 Argon2id 存储；管理命令可 `reset-password <username>` 和 `disable-user <username>`，后两者撤销用户所有现有会话。
- 不透明 HttpOnly、SameSite=Strict Cookie，数据库只保存认证令牌摘要。闲置 15 分钟、绝对 8 小时，预认证 5 分钟。`auth/me` 与 CSRF 查询不延长闲置时间。
- 写请求必须同 Origin、JSON、有效 CSRF。允许 Host 固定，不信任转发身份或 IP 头；最大 POST 请求体 32 KB。
- 登录失败按用户名及连接来源节流；预认证会话分配也有限流。错误不回显密码或供应商响应。
- 同一对话同时只处理一个请求；客户端每轮产生请求 UUID，重复 UUID 回放已保存答案而不重复请求模型。失败请求不自动重试；该机制不等于未来转账幂等方案。
- `.env` 和 `.local/` 均被 Git 忽略。后者保存数据库、会话和聊天，属于本地运行数据，不应上传分享。
- 本地启动入口固定回环监听、单进程、禁用代理转发头；`BANK_LOCAL_HTTP=true` 是显式的本机 HTTP 例外。应用默认不允许 HTTP，HTTPS 配置使用 Secure Cookie。

这是竞赛开发环境。不能将启动参数改为公网、多 worker 或反向代理后就视为生产银行服务；TLS、部署身份、审计、数据治理及生产加固需要单独设计。

## 5. 检查与人工验收

```powershell
python -m pytest -q
python -m ruff check --no-cache src tests
python -m ruff format --no-cache --check src tests
python -m pip check
```

如果系统临时目录不可写，可将 `TEMP` 和 `TMP` 指向本机可写的临时目录再执行；不要降低数据库或认证校验。Windows 受限沙箱还可能阻断 asyncio 所需的本机 socket，此时应在有本机网络权限的终端测试。

手工检查：创建两位用户，分别登录核对隔离；查看账户和筛选流水；问余额与最近支出；刷新确认对话保留；新建对话；退出后确认无法访问账户 API；在窄屏重复上述交互。真实模型接入后额外确认工具调用、供应商错误、超时和费用预算。

## 6. 只读接口速查

认证端点及 Cookie / CSRF 规则见 [认证契约](authentication.md)。以下业务端点均要求登录；POST 另需同 Origin、JSON 和 CSRF。客户端不能提交或覆盖用户身份。

| 请求 | 输入与返回 |
| --- | --- |
| `GET /api/health` | 环境与 Agent 模式、是否需要本地创建用户；不返回密钥 |
| `GET /api/accounts` | 当前用户账户数组和服务端状态快照 |
| `GET /api/accounts/{account_id}` | 本人的单个账户；不存在和越权统一 404 |
| `GET /api/transactions` | 可选 `account_id`，`limit` 为 1–30；本人最近流水 |
| `GET /api/conversations` | 本人最近 20 个对话的 ID 和创建时间 |
| `POST /api/conversations` | 严格空对象 `{}`；返回新对话 ID |
| `GET /api/conversations/{id}` | 本人对话的最近 50 回合，含成功、失败或未完成状态 |
| `POST /api/chat` | 仅接受 `conversation_id`、UUID `request_id`、1–2000 字符 `message`；返回 `answer`、`traces`、`mode`，首次成功另含快照 |

同一请求 ID 改变消息返回 409，同一对话同时处理返回 409；模型故障、轮次 / 上下文上限或超时返回明确 502 错误码。数据库不可用返回 503，不回退到默认身份。新增资金 API、错误与授权流程见 [模拟银行业务契约](banking-services.md)，没有向模型暴露写权限。

工具协议参考：[官方函数调用说明](https://developers.openai.com/api/docs/guides/function-calling)。这不是安全审计或竞赛验收证书。
