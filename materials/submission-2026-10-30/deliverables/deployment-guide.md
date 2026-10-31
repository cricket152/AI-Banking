# AI-Banking 部署说明

## 1. 适用环境

最低要求Python 3.12+；已验证环境为Windows / Python 3.14.6完整235项回归，以及新建Python 3.13环境的锁文件安装、依赖一致性与39项定向测试。采用单进程SQLite、本机回环HTTP，无需Node或前端编译。公网运行需独立配置认证、TLS和会话部署。

源码位于source-and-deployment.zip中的AI-Banking目录。新目录解压后，使用submission/package-manifest.json核对文件及SHA256；submission/archive-info.json记录功能基线和打包时Git HEAD。压缩包不含.env、运行数据库或实际凭据。

## 2. 新目录安装

在源码根目录用PowerShell执行：
```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c requirements-dev.lock
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m ai_banking.auth.cli create-user demo_user
.\.venv\Scripts\python.exe -m ai_banking
```
密码由终端隐藏输入并确认，没有默认密码。用户名3-32位、以字母开头的字母/数字/下划线；本地密码允许1-128字符。新建账号在事务中初始化隔离虚构账户与流水。所有相对路径以项目根目录为基准。

依赖安装需可访问包源；当前交付不包含离线wheel仓库。锁文件作为pip约束使用，不擅自升级包。已有.env时保留，不执行覆盖。模型密钥仅放本机.env或服务端环境变量。

## 3. 最小离线配置与健康检查

示例配置仅用于新目录：
```dotenv
BANK_ORIGIN=http://127.0.0.1:8000
BANK_LOCAL_HTTP=true
BANK_DATABASE=.local/banking.sqlite3
AGENT_MODE=offline
AGENT_TRACE_CONTENT=false
LANGSMITH_TRACING=false
```
复制.env.example后检查并编辑对应项，不要追加同名变量制造歧义。系统环境变量优先于.env。打开与BANK_ORIGIN完全一致的地址；localhost与127.0.0.1不可混用。
```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```
正常返回status=ok、simulated=true；有账号后setup_required=false，新库银行表就绪时bank_ready=true。健康检查不证明模型已完成一次真实调用。

## 4. 模型模式（可选）

在服务端.env将AGENT_MODE改为model，填写MODEL_BASE_URL（实际供应商HTTPS基础地址）、MODEL_API（responses或chat）、MODEL_NAME和MODEL_API_KEY。不要把中文占位值当作真实配置；供应商须支持函数工具和对应Schema。重启后页面显示模式和配置型号。模型模式会发送提问、历史与本人模拟财务数据；不静默降级或自动重试失败请求。

默认输出预算1500 tokens、上下文预算32000为本地估算；推理模型可能把输出预算用于推理，需按真实供应商核实，不保证一次成功。LangSmith可选，若启用需按requirements-observability.lock安装observability extra，不能误称默认部署依赖或可靠账本。

## 5. 功能与截图复现

默认样本不足三笔周期流水时，“疑似订阅”为空是预期。不要为演示修改既有运行库。
如需复现材料环境，使用包内submission/demo-environment.py，以项目根目录为工作目录运行该脚本。它显式构造Settings，不读取.env，使用独立.local/materials-reproduction-2026-10-30.sqlite3，监听127.0.0.1:8003，账号reviewer密码由操作者首次设置。Agent为明确标注的确定性脚本，无供应商调用；真实工具和执行器处理操作。重复运行保留状态，使用首次密码。

操作顺序：登录→账单洞察→异常原流水→订阅证据确认弹窗→密码复核载入虚构联系人→选择日常账户/云盘订阅/同事张明4712/1元→预览→保存→交给助手→每笔独立确认→核对2/2回执。该脚本不能评估真实模型能力。

## 6. 常见故障

| 现象 | 检查与处理 |
| --- | --- |
| WinError 10048 / 端口占用 | Get-NetTCPConnection -LocalPort 8000 -State Listen；核对OwningProcess和命令行，不结束未知服务。需要时改BANK_ORIGIN端口并重启 |
| netstat无监听仍无法绑定 | 检查Windows保留端口：netsh interface ipv4 show excludedportrange protocol=tcp；选另一个可用端口，不修改系统保留范围 |
| ORIGIN_REJECTED / HOST_REJECTED | 浏览器Origin、Host与BANK_ORIGIN的域名、协议、端口完全一致 |
| CSRF_REJECTED | 刷新并重新登录；不关闭CSRF校验。直接API调用按应用CSRF引导和Cookie流程执行 |
| MODEL_RESPONSE_INCOMPLETE | 供应商响应未完成，检查模型输出预算；先核对原操作，不换编号重新付款 |
| CONTEXT_BUDGET_EXCEEDED | 缩小输入或重新明确策略/目标；先核对后端状态，不重做已完成步骤 |
| outcome_unknown / 503回执失败 | 查询原操作，保留预占；不能当成肯定失败重新转账 |

## 7. 旧库、备份与停止

新目录新库自动初始化。旧库不随启动自动升级。只有用户已确认目标、备份与影响后，才执行`python -m ai_banking.banking.cli upgrade`并按终端提示明确同意；命令先做SQLite备份，再增表并检查引用。本文不授权对现有用户库执行迁移。

Ctrl+C停止前台服务；确认所属进程后再操作后台服务。备份、恢复或搬移数据库前先停止写入，使用SQLite备份机制或在完全停止后复制；不要在运行时只复制主文件漏掉WAL，也不要覆盖既有数据来“重置演示”。

## 8. 验证与复现

执行test-cases.md命令并记录日志。当前工作树在Python 3.14.6通过235项自动化（含前端浏览器冒烟1项）；另以新建Python 3.13 venv按`requirements-dev.lock`安装`.[dev]`，`pip check`通过并完成39项核心/前端定向测试。验证结论适用于上述Windows环境。目标环境或供应商发生变化时，按同一测试入口重新验证。
