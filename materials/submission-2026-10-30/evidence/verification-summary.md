# 本轮素材核验

- 当前工作树完整 pytest 回归：235 passed（Python 3.14.6 `.venv`；运行前在进程内清理 Windows 异常 `NO_PROXY` 值）；前端浏览器冒烟单独报告 `1 passed`，其结果已包含在全量计数中。
- Ruff check：All checks passed；Ruff format --check：43 files already formatted；`pip check`：No broken requirements found；`git diff --check`、新增 JavaScript `node --check` 均通过。
- 浏览器：独立合成库、脚本化Agent、真实工具与执行器；逐笔确认完成取消订阅与1元转账，2/2步；14张PNG。未调用真实供应商，不增加真实模型评测样本。
- 架构：Archify 3.2.0 showcase，当前review-3的validate/deliver/check/browser-check通过；visual-check四个明暗/尺寸状态自动测量通过。已检查原生PNG与对应页面布局；自动回执仍区分visualReview pending和人工观察，不改写工具回执。
- 归档：79个文件，268637字节，CRC和逐文件SHA256与清单一致；没有.env、数据库、虚拟环境、真实凭据或浏览器会话。未在全新机器安装验证。
- 来源：用户提交页面原图已收入；可选项名称未显示、格式和署名等缺口保留。

此为材料审校记录，不是正式提交或独立安全审计。可编辑PPTX已生成并通过10页结构与视觉检查，仍非正式提交；技术与安全PDF仍为历史导出，须由修订源稿重导后复核。真实模型未配置，新增能力专项评测未运行/未完成；团队署名、独立队友审查与正式提交仍待完成。冻结提交为 `9389868`，标签 `freeze-2026-10-31-v1.6` 已推送并完成远程核对。另以新建Python 3.13环境按锁文件安装并通过`pip check`，完成39项核心/前端定向测试；Python 3.12、全新机器与其他OS仍未验证。

- 截图复现脚本：Ruff lint / format通过；TestClient验证健康检查、合成用户登录和首页均200。脚本模式，不调用供应商。
- 源码ZIP常见密钥/私钥格式扫描无命中；此为有限模式检查，不能代替最终敏感信息人工复核。
- 日期场景计划的材料边界：仅保存日期与预算；创建时可用余额校验不产生预留；用户手动点击后才创建待确认操作，Agent只读。
- git diff --check通过；本文件仅记录submission-2026-10-30材料核验；冻结提交已推送并完成远程分支/标签核对。
