# LangSmith 接入与验证

当前使用可选 LangSmith Python SDK，为已有 Agent 添加可视化追踪。没有迁移到 LangGraph，没有改变模型消息、固定工具列表、授权与银行执行器。接入前的完整代码已提交本地 `27578b6`；本次 LangSmith 改动与该提交分开。

## 1. 创建 API Key

1. 打开 [LangSmith](https://smith.langchain.com/)，注册或登录，选定项目使用的 workspace。
2. 打开 **Settings → API Keys → API Key**。
3. 优先选择 **Tracing Only**，填写用途，例如 `ai-banking-local`，选择目标 workspace 和过期时间，再点击 **Create API Key**。这种 Key 只允许提交追踪和创建项目，不具备读取已有轨迹或管理账号的权限。
4. Key 仅在创建时显示，立即保存到本机 `.env`，不要粘贴到聊天、截图、代码或前端设置中。
5. 若当前部署没有 Tracing Only 选项，可参考官方说明，使用当前账号有权创建的 Personal Access Token 或限定 workspace 的 service key；不要自行更改组织权限。

菜单和权限以 [官方创建账号与 API Key 文档](https://docs.langchain.com/langsmith/create-account-api-key)为准。LangSmith Key 与模型供应商的 `MODEL_API_KEY` 是两个不同凭据。

## 2. 安装可选依赖

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,observability]" -c requirements-dev.lock -c requirements-observability.lock
```

本机已安装并验证 `langsmith==0.14.12`；新增约束只记录 SDK 的增量依赖，没有升级原有依赖。基础安装不要求 LangSmith；关闭时不导入 SDK、不上传追踪。SDK 缺失时业务继续，终端提示安装方法，健康检查显示 `missing_sdk`。

## 3. 配置连接

保留已有 `.env`，只添加或修改以下变量：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=替换为你刚创建的LangSmithKey
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=ai-banking-local
LANGSMITH_WORKSPACE_ID=
LANGSMITH_TRACE_CONTENT=false
```

- 上述 endpoint 是官方默认 GCP US 地址。使用其他区域或部署时，从对应 workspace 的配置说明复制 API endpoint；不要填写网页地址。Key、workspace 和 endpoint 必须属于匹配的环境，应用仅接受 HTTPS 且不允许 URL 携带凭据或查询参数。
- Key 可访问多个 workspace 时，明确填写目标 `LANGSMITH_WORKSPACE_ID`；在 **Settings → General** 查找 Workspace ID。仅一个 workspace 的 Key 可留空。
- `LANGSMITH_PROJECT` 是追踪项目名；服务端在有创建项目权限时可于首次提交创建，否则使用自己有权限的已有项目。新版本界面可能同时显示 agent / environment，按对应项目查找。
- `LANGSMITH_TRACE_CONTENT` 默认关闭，只保留阶段、耗时、关联 ID 和实际 usage，不上传对话 / 工具正文。仅在使用合成数据并确有需要时显式设为 `true`；SDK 的 `LANGSMITH_HIDE_INPUTS=true`、`LANGSMITH_HIDE_OUTPUTS=true` 也可进一步隐藏对应内容。
- LangSmith 内容开关与终端 `AGENT_TRACE_CONTENT` 独立。只关终端日志不会关闭云端采集；关闭云端需设置 `LANGSMITH_TRACING=false` 并重启。
- 已有系统环境变量优先于 `.env`，配置修改后须重新启动服务。

开启后默认只向指定 LangSmith 服务发送运行阶段、耗时、关联 ID 和 usage；显式设置 `LANGSMITH_TRACE_CONTENT=true` 后才上传脱敏后的输入 / 输出副本。内容脱敏覆盖已知模型 / 追踪 Key、凭据字段、常见敏感模式及长数字，移除加密推理，转义控制字符，截断单字符串和长列表；不采集认证对象、HTTP Header、密码接口、任意对象或 SDK 自动环境信息。模式匹配不能识别所有未标记的秘密；正文追踪只使用虚构数据，不要把真实银行数据用于开发追踪。

## 4. 先执行独立连接自检

```powershell
.\.venv\Scripts\python.exe -m ai_banking.observability check
```

该命令只上传一条名为 **LangSmith 连接自检** 的合成追踪，不读取银行数据，不调用模型，也不产生模型费用。命令成功退出后，在目标 workspace 的 **Tracing / Tracing Projects** 中找到 `ai-banking-local` 并打开该记录。若页面未出现，检查 workspace、项目过滤和时间范围；SDK 成功提交不等于页面过滤正确。

未开启、配置不完整或缺少 SDK 会明确失败；网络或鉴权失败返回非零退出码，不打印 Key 或服务端响应正文。自检最多等待 5 秒确认结果，超时不能视为成功；不要将此命令输出与银行交易回执混淆。

## 5. 查看实际 Agent 轨迹

```powershell
.\.venv\Scripts\python.exe -m ai_banking
```

登录 [本地工作台](http://127.0.0.1:8000)，新建对话并问“查询我的账户余额”。模型模式通常得到以下树形轨迹：

```text
Agent 对话（chain，带 request_id / thread_id）
├─ 模型调用（llm：输入消息、公开思考 / 回复、工具调用、usage）
├─ list_accounts（tool：参数、结果）
└─ 模型调用（llm：工具结果参与后续回答）
```

离线模式仍会记录整轮与本地工具，但没有 LLM 节点或模型 token。供应商未返回的推理、token 或费用不被编造。模型名称和供应商有明确元数据；自定义型号的费用显示还取决于 LangSmith 的模型定价配置，本项目不硬编码价格。

`thread_id` 取自应用对话 ID，可以关联同一对话的多轮请求；`request_id` 对应终端请求 ID。重复请求命中本地回执时不再次调用模型，也不额外创建整轮云端追踪。

整轮完成后由独立后台线程上传，因此等待中的节点不会逐 token 实时出现在页面。队列最多保留 32 轮；满时丢弃调试轨迹并提示，不阻塞业务。上传异常不会重试模型或资金操作，也不会把业务成功改成失败；一棵树上传中断时可能只有部分节点。正常退出最多等待 2 秒，尚未送达的轨迹可能丢失。追踪用于调试，不是账本、恢复检查点或可靠审计存储。

## 6. 核对连接状态和排错

打开 [健康检查](http://127.0.0.1:8000/api/health)，查看新增 `langsmith` 字段：

| status | 含义 |
| --- | --- |
| `disabled` | 本次进程未启用追踪 |
| `ready` | SDK 就绪，尚未确认首次上传；不表示 Key 已验证 |
| `connected` | 至少一轮完整追踪已成功提交 |
| `missing_sdk` | 缺少可选依赖；业务仍可使用 |
| `initialization_error` | SDK 初始化失败；检查安装和配置 |
| `upload_error` | 上传失败；检查 Key、区域、workspace 权限、有效期、网络与代理 |

还会返回成功、失败和丢弃计数，不返回 Key、认证信息或服务端异常正文。缺少 Key、非法 endpoint 等本地配置错误在启动时直接提示，避免误以为已开启追踪。

真实云端连通由用户填入自己的 Key 后运行自检确认。2026-10-23 用户已提供自检上传成功及项目中成功记录的截图，确认合成追踪可见；实际模型 / 工具轨迹和费用显示仍待人工验收。自动化测试通过真实 SDK 和本地拦截的 HTTP 请求验证协议，没有使用用户真实 Key。

## 7. 本地验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_observability.py tests/test_tracing.py -v
.\.venv\Scripts\python.exe -m pytest -q
```

新增测试覆盖 SDK 上传请求、父子关联、两种模型协议、凭据 / 加密推理过滤、内容开关、缺依赖、队列上限、并发隔离、上传阻塞与失败、重复请求和连接自检。SDK 专项测试需要可选依赖，未安装时会明确跳过；测试不访问真实 LangSmith 或模型。

参考：[官方自定义埋点](https://docs.langchain.com/langsmith/annotate-code)、[LLM 消息与 usage 格式](https://docs.langchain.com/langsmith/log-llm-trace)、[输入输出隐私控制](https://docs.langchain.com/langsmith/mask-inputs-outputs)。
