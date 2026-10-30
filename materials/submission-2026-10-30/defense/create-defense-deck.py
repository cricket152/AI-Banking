from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
DEFENSE = Path(__file__).resolve().parent
OUT = DEFENSE / "AI-Banking-defense.pptx"
FONT = "Microsoft YaHei"

COLORS = {
    "ink": "1E2C33",
    "muted": "626F70",
    "paper": "F4F1EA",
    "white": "FFFEFB",
    "line": "D8D1C5",
    "teal": "2D786A",
    "teal_pale": "E5F0EB",
    "gold": "A66B2F",
    "gold_pale": "F4E9D8",
    "red": "A84E48",
    "red_pale": "F4E7E5",
    "blue_pale": "E7EEF0",
    "green": "397354",
}


def color(name):
    return RGBColor.from_string(COLORS.get(name, name))


def set_font(run, size, color_name="ink", bold=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color(color_name)


def text(slide, value, x, y, w, h, size=16, color_name="ink", bold=False,
         align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP, margin=0.02):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(margin)
    frame.margin_right = Inches(margin)
    frame.margin_top = Inches(margin)
    frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    for index, line in enumerate(value.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.space_before = Pt(0)
        paragraph.space_after = Pt(0)
        paragraph.line_spacing = 1.0
        run = paragraph.add_run()
        run.text = line
        set_font(run, size, color_name, bold)
    return shape


def rect(slide, x, y, w, h, fill_name="white", line_name=None, line_width=0.8):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color(fill_name)
    if line_name:
        shape.line.color.rgb = color(line_name)
        shape.line.width = Pt(line_width)
    else:
        shape.line.fill.background()
    return shape


def line(slide, x1, y1, x2, y2, color_name="line", width=1.0):
    shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    shape.line.color.rgb = color(color_name)
    shape.line.width = Pt(width)
    return shape


def image_fit(slide, path, x, y, w, h, frame=True):
    path = Path(path)
    if frame:
        rect(slide, x, y, w, h, "white", "line", 0.8)
    with Image.open(path) as source:
        iw, ih = source.size
    scale = min(w / iw, h / ih)
    pw, ph = iw * scale, ih * scale
    px, py = x + (w - pw) / 2, y + (h - ph) / 2
    return slide.shapes.add_picture(str(path), Inches(px), Inches(py), Inches(pw), Inches(ph))


def fresh_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color("paper")
    return slide


def header(slide, section, title_text, subtitle):
    text(slide, section.upper(), 0.78, 0.22, 11.8, 0.22, 10, "teal", True)
    text(slide, title_text, 0.78, 0.52, 11.8, 0.50, 25, "ink", True)
    text(slide, subtitle, 0.80, 1.08, 11.8, 0.32, 13, "muted")
    line(slide, 0.78, 1.52, 12.55, 1.52, "line", 0.9)


def footer(slide, number):
    line(slide, 0.78, 7.06, 12.55, 7.06, "line", 0.7)
    text(slide, "AI-BANKING  |  本地模拟 · 虚构数据 · 脚本化演示", 0.80, 7.12, 8.8, 0.19, 8.5, "muted")
    text(slide, f"{number:02d} / 10", 11.60, 7.11, 0.92, 0.20, 9, "muted", align=PP_ALIGN.RIGHT)


def cell(slide, value, x, y, w, h, size=13, color_name="ink", bold=False):
    text(slide, value, x + 0.12, y + 0.08, w - 0.24, h - 0.16, size, color_name, bold, valign=MSO_ANCHOR.MIDDLE)


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "AI-Banking 受约束的个人银行助手"
    prs.core_properties.subject = "竞赛答辩演示"
    prs.core_properties.keywords = "AI-Banking, 模拟银行, 受控操作"

    # 1. Cover
    slide = fresh_slide(prs)
    rect(slide, 0, 0, 5.48, 7.5, "ink")
    rect(slide, 0.74, 0.65, 0.50, 0.50, "paper")
    text(slide, "A", 0.75, 0.68, 0.48, 0.44, 22, "ink", True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    text(slide, "AI-BANKING", 1.42, 0.66, 3.3, 0.30, 15, "paper", True, valign=MSO_ANCHOR.MIDDLE)
    text(slide, "本地模拟工作台", 1.42, 0.98, 3.3, 0.24, 9, "paper")
    line(slide, 0.78, 1.58, 1.48, 1.58, "gold", 2.2)
    text(slide, "AI-Banking", 0.78, 1.90, 4.2, 0.58, 34, "paper", True)
    text(slide, "受约束的个人银行助手", 0.80, 2.70, 4.28, 0.48, 22, "paper", True)
    text(slide, "账单依据可追溯，\n业务操作由用户确认，\n最终状态以后端账本为准。", 0.82, 3.48, 4.20, 1.32, 17, "paper")
    rect(slide, 0.80, 5.20, 3.64, 0.48, "teal")
    text(slide, "10页  ·  预计讲解 8分40秒", 0.95, 5.29, 3.34, 0.23, 12, "white", True, valign=MSO_ANCHOR.MIDDLE)
    text(slide, "本地模拟  /  虚构数据  /  演示回复脚本化", 0.82, 6.03, 4.18, 0.35, 10, "paper")
    image_fit(slide, ROOT / "images" / "02-overview.png", 5.95, 1.12, 6.62, 4.60, frame=True)
    text(slide, "个人财务工作台 · 模拟环境截图", 6.00, 5.88, 6.50, 0.28, 11, "muted", align=PP_ALIGN.CENTER)
    line(slide, 0.78, 7.06, 12.55, 7.06, "line", 0.7)
    text(slide, "团队与成员信息：TODO  |  未上传，未正式提交", 0.80, 7.12, 8.8, 0.19, 8.5, "muted")
    text(slide, "01 / 10", 11.60, 7.11, 0.92, 0.20, 9, "muted", align=PP_ALIGN.RIGHT)

    # 2. Problem framing
    slide = fresh_slide(prs)
    header(slide, "01 / 设计目标", "金融Agent的难点，不止是听懂", "目标是让依据、边界与操作状态都能被用户核对。")
    blocks = [
        (0.80, "blue_pale", "01  有依据", "周期候选与异常线索\n都要能展开到原始流水。", "规则提示不是欺诈结论。"),
        (4.82, "gold_pale", "02  目标清楚", "同名对象、账户和金额\n需要落到明确选项。", "查询命中不等于理解保证。"),
        (8.84, "teal_pale", "03  状态分明", "保存、待确认、已完成\n分别对应不同后端状态。", "模型文字不是资金回执。"),
    ]
    for x, fill_name, label, body, note in blocks:
        rect(slide, x, 2.02, 3.70, 2.54, fill_name)
        text(slide, label, x + 0.22, 2.30, 3.22, 0.35, 18, "ink", True)
        text(slide, body, x + 0.22, 2.88, 3.22, 0.84, 16, "ink")
        text(slide, note, x + 0.22, 4.12, 3.22, 0.24, 10.5, "muted")
    text(slide, "演示主线", 0.82, 5.03, 1.2, 0.26, 11, "teal", True)
    flow = ["查询", "核对", "预览", "独立确认", "核对回执"]
    x = 0.82
    for index, label in enumerate(flow):
        rect(slide, x, 5.48, 1.78 if index != 3 else 2.05, 0.68, "white", "line", 0.8)
        text(slide, label, x + 0.08, 5.64, (1.62 if index != 3 else 1.89), 0.27, 13, "ink", True, align=PP_ALIGN.CENTER)
        x += (1.95 if index != 3 else 2.22)
        if index < len(flow) - 1:
            text(slide, ">", x - 0.02, 5.66, 0.26, 0.24, 15, "gold", True, align=PP_ALIGN.CENTER)
            x += 0.14
    footer(slide, 2)

    # 3. Capability and write boundaries
    slide = fresh_slide(prs)
    header(slide, "02 / 能力边界", "Agent读什么、能准备什么，写入从哪里发起", "卡片、日期场景计划与理财数据对Agent只读/解释；对应写操作由界面发起。")
    x0, y0 = 0.80, 1.84
    widths = [1.55, 2.55, 3.15, 4.45]
    headers = ["业务", "Agent", "写入路径", "明确边界"]
    xx = x0
    for width, label in zip(widths, headers):
        rect(slide, xx, y0, width, 0.52, "ink")
        cell(slide, label, xx, y0, width, 0.52, 12, "white", True)
        xx += width
    rows = [
        ("账单 / 订阅 / 转账", "查询；准备有限意图", "界面逐步确认，或在有效预授权范围内复核", "账单异常仅是线索；转账为模拟银行内部CNY"),
        ("卡片", "查询脱敏数据；无写工具", "界面发起；卡片写操作需密码再认证", "不连接真实卡组织或信用记录"),
        ("日期场景计划", "只读 / 解释；不能创建或下单", "界面保存日期/预算；用户手动点击下单再确认", "创建时校验余额，不冻结或预留资金"),
        ("理财", "查询 / 解释模拟数据", "界面申购/赎回并逐笔确认", "不连接真实产品，不保证收益"),
    ]
    y = y0 + 0.52
    for row_index, row in enumerate(rows):
        fill_name = "white" if row_index % 2 == 0 else "blue_pale"
        xx = x0
        for col_index, (width, value) in enumerate(zip(widths, row)):
            rect(slide, xx, y, width, 1.02, fill_name, "line", 0.6)
            cell(slide, value, xx, y, width, 1.02, 12 if col_index else 12.5, "teal" if col_index == 0 else "ink", col_index == 0)
            xx += width
        y += 1.02
    rect(slide, 0.80, 6.58, 11.70, 0.27, "gold_pale")
    text(slide, "“Agent只读”不等于“系统不可办理”：用户仍可在业务界面完成明确写操作。", 0.94, 6.60, 11.40, 0.20, 10.5, "ink", True)
    footer(slide, 3)

    # 4. Architecture and checks
    slide = fresh_slide(prs)
    header(slide, "03 / 系统链路", "从提问到记账，经过确定性的应用检查", "模型提出受限意图；身份、对象、步骤、确认与最终记账由应用和银行服务复核。")
    image_fit(slide, ROOT / "diagrams" / "agent-runtime.png", 0.80, 1.76, 5.63, 5.08, frame=True)
    checks = [
        ("A", "请求入口", "会话身份、Origin/Host、CSRF、长度与格式"),
        ("B", "每次工具调用", "白名单、参数Schema、本人数据归属"),
        ("C", "意图与任务约束", "固定步骤、对象/金额、状态和幂等约束"),
        ("D", "批准与执行", "逐笔确认或范围内预授权；SQLite事务复核"),
    ]
    y = 1.91
    for letter, title_text, body in checks:
        rect(slide, 6.82, y, 0.54, 0.54, "red_pale")
        text(slide, letter, 6.84, y + 0.06, 0.50, 0.38, 15, "red", True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
        text(slide, title_text, 7.58, y + 0.02, 4.62, 0.29, 15, "ink", True)
        text(slide, body, 7.58, y + 0.40, 4.62, 0.40, 11.5, "muted")
        y += 1.08
    rect(slide, 6.82, 6.30, 5.35, 0.48, "teal")
    text(slide, "查询返回数据  ·  操作结果回填  ·  账本回执为准", 6.98, 6.40, 5.04, 0.26, 11, "white", True, align=PP_ALIGN.CENTER)
    footer(slide, 4)

    # 5. Billing evidence
    slide = fresh_slide(prs)
    header(slide, "04 / 可解释账单", "异常是线索，不是欺诈结论", "演示中的餐饮支出为 ¥200；历史同类流水中位数为 ¥20。用户仍需核对原始凭证。")
    image_fit(slide, ROOT / "images" / "04-anomaly-evidence.png", 0.80, 1.82, 6.78, 4.72, frame=True)
    steps = [
        ("01", "规则提示", "本期支出相对等长前期区间明显变化。"),
        ("02", "原始凭证", "展开账户、商户、时间和金额流水。"),
        ("03", "用户判断", "正常消费也可能触发；不把线索说成欺诈。"),
    ]
    y = 2.06
    for number, title_text, body in steps:
        text(slide, number, 7.96, y, 0.58, 0.34, 14, "gold", True)
        text(slide, title_text, 8.64, y, 3.35, 0.34, 16, "ink", True)
        text(slide, body, 8.64, y + 0.45, 3.43, 0.70, 12.5, "muted")
        y += 1.35
    text(slide, "来源：虚构账本与确定性规则，不是模型评测结果。", 7.96, 6.24, 4.55, 0.30, 10, "red", True)
    footer(slide, 5)

    # 6. Subscription and fixed workflow
    slide = fresh_slide(prs)
    header(slide, "05 / 订阅与固定工作流", "订阅要先核对，固定联动也逐步确认", "下方截图展示“取消所选订阅后转固定金额”，不是生日/纪念日日期计划。")
    image_fit(slide, ROOT / "images" / "05-subscription-evidence.png", 0.80, 1.82, 5.70, 3.96, frame=True)
    image_fit(slide, ROOT / "images" / "12-workflow-complete.png", 6.94, 1.82, 5.45, 4.28, frame=True)
    text(slide, "周期证据与人工登记确认", 0.90, 5.90, 5.50, 0.26, 11, "ink", True, align=PP_ALIGN.CENTER)
    text(slide, "固定工作流的模拟后端回执（2/2步）", 6.98, 6.16, 5.35, 0.24, 10.5, "ink", True, align=PP_ALIGN.CENTER)
    rect(slide, 0.80, 6.56, 11.60, 0.28, "gold_pale")
    text(slide, "登记不扣款  ·  取消不退款  ·  未来少支出不是当前到账", 0.94, 6.60, 11.32, 0.20, 10.5, "ink", True, align=PP_ALIGN.CENTER)
    footer(slide, 6)

    # 7. Date scenario behavior
    slide = fresh_slide(prs)
    header(slide, "06 / 日期场景计划", "不预留资金，不自动下单", "Agent只读/解释计划；计划保存和下单由用户在业务界面发起。")
    text(slide, "计划记录仅包含", 0.82, 1.84, 1.65, 0.30, 11, "muted", True)
    rect(slide, 2.45, 1.78, 1.72, 0.48, "blue_pale")
    text(slide, "日期", 2.52, 1.88, 1.58, 0.24, 13, "ink", True, align=PP_ALIGN.CENTER)
    rect(slide, 4.30, 1.78, 1.72, 0.48, "gold_pale")
    text(slide, "预算", 4.37, 1.88, 1.58, 0.24, 13, "ink", True, align=PP_ALIGN.CENTER)
    stages = [
        (0.80, "01  创建计划", "校验当时可用余额。\n不冻结、不预留资金。", "界面写入"),
        (4.80, "02  用户决定", "用户自行查看、判断；\n手动点击界面下单按钮。", "无自动提醒 / 定时触发"),
        (8.80, "03  待确认操作", "生成待确认操作，\n后续仍走确认流程。", "无外部商户订单"),
    ]
    for x, title_text, body, label in stages:
        rect(slide, x, 2.70, 3.66, 2.44, "white", "line", 0.9)
        text(slide, title_text, x + 0.22, 2.98, 3.22, 0.34, 16, "teal", True)
        text(slide, body, x + 0.22, 3.60, 3.22, 0.82, 14, "ink")
        text(slide, label, x + 0.22, 4.72, 3.22, 0.24, 10.5, "muted", True)
    text(slide, ">", 4.48, 3.63, 0.24, 0.36, 18, "gold", True, align=PP_ALIGN.CENTER)
    text(slide, ">", 8.48, 3.63, 0.24, 0.36, 18, "gold", True, align=PP_ALIGN.CENTER)
    rect(slide, 0.80, 5.65, 11.66, 0.90, "ink")
    text(slide, "Agent权限", 1.04, 5.84, 1.30, 0.27, 12, "paper", True)
    text(slide, "只读 / 解释场景状态  ·  不能创建、修改或下单", 2.52, 5.80, 9.48, 0.40, 16, "white", True, valign=MSO_ANCHOR.MIDDLE)
    footer(slide, 7)

    # 8. Approval and UI writes
    slide = fresh_slide(prs)
    header(slide, "07 / 权限与确认", "审批范围绑定到账户、对象与额度", "预授权表单用于受限资金工作流；卡片、日期计划与理财写操作仍由界面发起。")
    image_fit(slide, ROOT / "images" / "14-authorization-scope.png", 0.80, 1.78, 5.78, 4.82, frame=True)
    text(slide, "图片展示转账/订阅工作流的预授权范围，不代表Agent拥有卡片或理财写权限。", 0.88, 6.66, 5.60, 0.28, 9.5, "muted")
    text(slide, "Agent只读 / 解释", 6.98, 1.93, 4.90, 0.33, 17, "teal", True)
    text(slide, "卡片 · 日期场景计划 · 理财", 6.98, 2.36, 4.90, 0.30, 13, "ink")
    line(slide, 6.98, 2.92, 12.35, 2.92, "line", 0.8)
    text(slide, "用户界面发起写操作", 6.98, 3.18, 4.90, 0.33, 17, "gold", True)
    text(slide, "卡片变更：密码再认证\n日期计划：手动按钮\n理财申购/赎回：逐笔确认", 6.98, 3.64, 5.00, 1.12, 13, "ink")
    line(slide, 6.98, 4.98, 12.35, 4.98, "line", 0.8)
    text(slide, "确认原则", 6.98, 5.22, 4.90, 0.32, 16, "red", True)
    text(slide, "范围、额度、期限与实际操作逐次复核。\n聊天中的“同意”不代替独立批准。", 6.98, 5.68, 5.10, 0.74, 12.5, "muted")
    footer(slide, 8)

    # 9. Verification status
    slide = fresh_slide(prs)
    header(slide, "08 / 验证范围", "代码与流程验证，不等于模型总成功率", "区分自动化回归、历史模型样本与尚未完成的评估。")
    panels = [
        (0.80, 3.67, "teal_pale", "235", "自动化测试通过", "全量 pytest 235 passed，\n其中前端浏览器冒烟1 passed"),
        (4.82, 3.67, "gold_pale", "35 / 36", "历史固定样本结构检查", "1条被输出预算保护拦截；\n不是模型业务成功率"),
        (8.84, 3.67, "red_pale", "未配置", "真实模型未配置", "专项评测未完成；独立队友审查、\nPython 3.12与全新机器仍未验证"),
    ]
    for x, w, fill_name, metric, title_text, body in panels:
        rect(slide, x, 2.08, w, 3.30, fill_name)
        text(slide, metric, x + 0.20, 2.38, w - 0.40, 0.66, 31 if metric != "未完成" else 25, "ink", True)
        text(slide, title_text, x + 0.20, 3.27, w - 0.40, 0.47, 15, "ink", True)
        text(slide, body, x + 0.20, 4.10, w - 0.40, 0.82, 12, "muted")
    rect(slide, 0.80, 5.78, 11.70, 0.78, "ink")
    text(slide, "测试中的模型HTTP由替身提供；截图为虚构数据与脚本化回复，不证明实时供应商能力。", 1.04, 5.97, 11.20, 0.38, 12, "white", True, valign=MSO_ANCHOR.MIDDLE)
    footer(slide, 9)

    # 10. Close and submission status
    slide = fresh_slide(prs)
    header(slide, "09 / 结论与提交边界", "明确展示已验证内容，也标出待补项目", "当前是材料审校稿，不是正式提交包。")
    rect(slide, 0.80, 1.90, 5.66, 3.78, "teal_pale")
    rect(slide, 6.82, 1.90, 5.66, 3.78, "gold_pale")
    text(slide, "可如实展示", 1.08, 2.20, 5.05, 0.40, 18, "teal", True)
    text(slide, "账单线索可展开到原始流水\n受控订阅/转账工作流逐步确认\n日期计划仅存日期/预算且不预留\n卡片/场景/理财Agent只读，写操作走界面", 1.08, 2.88, 5.00, 1.90, 14, "ink")
    text(slide, "提交前待完成", 7.10, 2.20, 5.05, 0.40, 18, "gold", True)
    text(slide, "补齐团队、分工与签署\n完成独立队友审查和专项模型评测\n按冻结版本重打包源码\n从修订源稿重导并复核技术/安全PDF", 7.10, 2.88, 5.00, 1.90, 14, "ink")
    rect(slide, 0.80, 5.98, 11.68, 0.62, "ink")
    text(slide, "证据可追溯  ·  权限可核对  ·  操作可拒绝", 1.06, 6.10, 11.16, 0.34, 18, "white", True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    footer(slide, 10)

    prs.save(OUT)
    print(f"Created {OUT} with {len(prs.slides)} slides")


if __name__ == "__main__":
    build()
