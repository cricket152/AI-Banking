# AI-Banking 测试用例与验收说明

## 1. 证据与执行方式

已有完整回归232项通过（含参数化节点），原日志31.83秒；本清单挑选30项关键自动化场景，不冒充全部232项的逐项描述。实际可执行测试在源码tests/，固定真实模型样本在evals/banking-agent.json。自动化模型HTTP为替身，不证明实际供应商持续可用或语义全项通过。

在源码根目录执行：
```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest --collect-only -q
.\.venv\Scripts\python.exe -m pytest -q tests/test_insights.py tests/test_transfer_workflows.py
.\.venv\Scripts\python.exe -m ruff check --no-cache src tests
.\.venv\Scripts\python.exe -m ruff format --no-cache --check src tests
```
定向执行语法：`python -m pytest -q tests/文件名.py::函数名`。测试使用独立临时数据库、固定时钟/故障注入与模拟HTTP；不要指向默认运行库。模型评测默认只列用例，显式--live才会读取供应商配置并产生调用成本，见源码docs/agent-evaluation.md。

## 2. 关键自动化用例

以下映射到已存在的函数。结果依据现有232项完整回归，参数化函数可展开多个实际节点；完整节点清单见test-nodeids.txt。

| 编号 | 可执行节点（tests/下） | 操作/输入 | 预期 |
| --- | --- | --- | --- |
| AUTH-01 | `test_application.py::test_password_storage_normalization_and_atomic_seed` | 创建用户并读取存储与初始流水 | 无明文密码；归一化用户名和初始化事务成立 |
| AUTH-02 | `test_application.py::test_login_rotates_session_and_no_raw_cookie_in_database` | 登录并检查旧会话和数据库 | 令牌轮换；数据库不存原始Cookie |
| AUTH-03 | `test_application.py::test_csrf_origin_host_and_content_type_boundaries` | 缺失/伪造CSRF与Origin/Host、错误类型 | 请求拒绝，不削弱校验 |
| AUTH-04 | `test_application.py::test_owner_isolation_for_accounts_transactions_and_chats` | 另一用户访问账户、流水与对话 | 不泄露跨用户数据 |
| AUTH-05 | `test_application.py::test_reset_and_disable_revoke_all_sessions` | 重置密码或停用账号 | 旧会话失效 |
| FUND-01 | `test_banking.py::test_manual_transfer_requires_real_bound_challenge_and_balances_ledger` | 准备、挑战、批准与查询账本 | 独立确认后转账；双边平衡 |
| FUND-02 | `test_banking.py::test_task_step_idempotency_and_parameter_binding` | 重复步骤、改变原参数 | 相同请求复用；参数冲突拒绝 |
| FUND-03 | `test_banking.py::test_concurrent_balance_contention_never_overdraws` | 并发争用有限余额 | 不能透支 |
| FUND-04 | `test_banking.py::test_concurrent_budget_reservations_cannot_exceed_limit` | 并发预授权预占 | 累计不超限 |
| FUND-05 | `test_banking.py::test_fault_rollback_unknown_result_preserves_reservation_until_reconciled` | 在不同故障点中断执行 | 回滚或保留未知预占；无盲重发 |
| FUND-06 | `test_banking.py::test_lost_response_after_commit_queries_original_operation_and_does_not_pay_twice` | 提交后丢失响应并核对原操作 | 原操作成功；不重复扣款 |
| FUND-07 | `test_banking_edges.py::test_policy_budget_survives_logout_and_restart` | 退出与重启后读取授权 | 预算不重置 |
| FUND-08 | `test_banking_edges.py::test_approval_challenge_bound_to_session_and_exact_summary` | 换会话或修改确认摘要 | 挑战拒绝 |
| BILL-01 | `test_insights.py::test_report_comparison_refunds_transfers_and_evidence` | 两期、退款、转账和证据查询 | 区间统计与分类依据一致 |
| BILL-02 | `test_insights.py::test_evidence_pages_are_complete_scoped_and_validate_dates` | 分页读区间流水、非法日期和越权 | 完整且按归属，非法输入拒绝 |
| SUB-01 | `test_insights.py::test_candidates_explain_evidence_without_writing` | 查询周期候选并对比数据库 | 附证据、无写入 |
| SUB-02 | `test_insights.py::test_confirm_is_explicit_idempotent_and_does_not_grant_or_move_funds` | 显式登记并重复提交 | 仅一次登记，不扣款、不授权 |
| SUB-03 | `test_insights.py::test_candidate_confirmation_rejects_foreign_and_changed_evidence` | 跨用户或变更证据后确认 | 拒绝，不用旧预览写入 |
| SUB-04 | `test_insights.py::test_concurrent_confirm_only_registers_once` | 并发登记候选 | 只产生一次登记 |
| PAYEE-01 | `test_transfer_workflows.py::test_payee_search_ambiguity_notes_and_user_isolation` | 同名、备注、尾号和跨用户查询 | 歧义需澄清；不跨用户 |
| PAYEE-02 | `test_transfer_workflows.py::test_demo_contacts_are_explicit_private_idempotent_and_cannot_login` | 载入、重复载入、尝试登录联系人 | 显式私有且幂等；联系人不能登录 |
| PAYEE-03 | `test_transfer_workflows.py::test_loading_contacts_does_not_expand_existing_grant` | 先授权后载入新联系人 | 旧授权不扩容 |
| PLAN-01 | `test_transfer_workflows.py::test_plan_preview_and_creation_do_not_move_funds_or_authorize` | 预览并创建方案 | 资金与授权不变 |
| PLAN-02 | `test_transfer_workflows.py::test_plan_creation_revalidates_balance_notes_and_subscription_evidence` | 修改余额、备注或订阅后创建 | 原预览失效 |
| PLAN-03 | `test_transfer_workflows.py::test_plan_blocks_out_of_order_changed_amount_and_new_id_replay` | 跳步、改金额、换编号重放 | 拒绝绕过固定方案 |
| PLAN-04 | `test_transfer_workflows.py::test_unsuccessful_plan_step_stops_following_payment` | 前一步失败、拒绝、过期等 | 后一步不付款 |
| PLAN-05 | `test_transfer_workflows.py::test_preauthorized_plan_still_rechecks_scope_and_only_executes_selected_steps` | 选择预授权执行固定方案 | 仍复核范围，仅执行所选步骤 |
| PLAN-06 | `test_transfer_workflows.py::test_model_plan_continues_after_each_independent_approval` | 两种协议的模拟HTTP，逐笔批准 | 正确续办；不是实际供应商能力证明 |
| PLAN-07 | `test_transfer_workflows.py::test_plan_does_not_use_future_savings_as_current_money` | 余额不足但未来有节省 | 不能用未来节省充当当前现金 |
| CTX-01 | `test_context.py::test_budget_failure_pauses_new_writes_until_policy_reselected` | 超预算后提出新写意图 | 暂停新增写操作，明确重选策略后处理 |

## 3. 人工审核结果（已完成）

前置：独立虚构账号；按部署指南启动；准备有余额的付款账户、已登记订阅及明确收款对象。预授权只在独立模拟环境建立。本表MAN-01至MAN-10已完成人工审核，结果通过。审核人角色：项目负责人；审核日期：2026-10-30；审核结论：通过。既有截图仍按原模式标注，人工反馈不改变其脚本化演示属性。

| 编号 | 步骤 | 预期 | 状态 |
| --- | --- | --- | --- |
| MAN-01 | 选择账单日期并展开异常与分类流水 | 日期、总额和原流水一致，规则说明完整 | 已人工审核（通过） |
| MAN-02 | 核对三次周期候选，关闭登记弹窗；再显式登记 | 关闭不写；登记一次、不扣款、不授权 | 已人工审核（通过） |
| MAN-03 | 模型模式说“给张明转1元” | 有两位张明时先列备注/尾号澄清，不擅选 | 已人工审核（通过） |
| MAN-04 | 核对转账确认单后关闭或拒绝 | 不执行，状态与余额正确 | 已人工审核（通过） |
| MAN-05 | 创建固定取消后转账方案，逐笔确认 | 先取消再转账，2/2回执；未来节省不是现金 | 已人工审核（通过） |
| MAN-06 | 方案中途刷新、重新进入，再要求继续 | 恢复实际状态，成功步骤不重做 | 已人工审核（通过） |
| MAN-07 | 先取消一项，再拒绝转账 | 停止后续，不自动恢复已取消订阅 | 已人工审核（通过） |
| MAN-08 | 指定小额预授权，提出超范围对象/金额 | 后端拒绝，不自动扩大授权或改模式 | 已人工审核（通过） |
| MAN-09 | 长对话或改变目标后再要求付款 | 澄清必要对象和金额，以后端状态为准 | 已人工审核（通过） |
| MAN-10 | 浏览器390宽、键盘与缩放核对确认单 | 主要内容、按钮与状态可操作、无误导裁切 | 已人工审核（通过） |

人工审核结论由负责人确认；本材料未附逐次原始日志，不代填型号或操作者签名。后续回归记录应填写代码快照、模式/模型、操作者、日期、输入、实际结果、原操作编号和余额/账本证据；编号保存在受控记录中，不附会话Cookie或密钥。失败须保留，不以调大预算的成功覆盖原失败。

## 4. 已知未覆盖与通过标准

历史35/36仅结构断言，不当作97.2%语义成功率；旧留出样本已用于诊断。列示人工用例已审核通过；独立真实模型统计样本、正式队友验收、最低Python版本与干净依赖安装、真实设备专项、公网与生产安全审计不在本次确认结论内。

自动化通过要求退出码0且原测试不删减；人工验收以真实账本、归属与状态为准，模型一句“成功”不足以通过。任一越权、重复扣款、超额或双边不平衡均须阻止冻结交付。
