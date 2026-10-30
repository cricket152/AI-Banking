# 本轮素材核验

- pytest -q：222 passed in 31.83s；退出码0，原始日志pytest.txt。
- Ruff check：All checks passed；Ruff format --check：36 files already formatted。
- 浏览器：独立合成库、脚本化Agent、真实工具与执行器；逐笔确认完成取消订阅与1元转账，2/2步；14张PNG。未调用真实供应商，不增加真实模型评测样本。
- 架构：Archify 3.2.0 showcase，当前review-3的validate/deliver/check/browser-check通过；visual-check四个明暗/尺寸状态自动测量通过。已检查原生PNG与对应页面布局；自动回执仍区分visualReview pending和人工观察，不改写工具回执。
- 归档：79个文件，268637字节，CRC和逐文件SHA256与清单一致；没有.env、数据库、虚拟环境、真实凭据或浏览器会话。未在全新机器安装验证。
- 来源：用户提交页面原图已收入；可选项名称未显示、格式和署名等缺口保留。

此为工作树素材准备，不是正式提交或独立安全审计。PPT、最终PDF/DOCX、真实模型新增语义验收、冻结版本和干净环境复现尚待完成。

- 截图复现脚本：Ruff lint / format通过；TestClient验证健康检查、合成用户登录和首页均200。脚本模式，不调用供应商。
- 源码ZIP常见密钥/私钥格式扫描无命中；此为有限模式检查，不能代替最终敏感信息人工复核。
- git diff --check通过；未改业务实现、未提交/推送。
