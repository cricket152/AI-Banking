/** 跨场景计划：日期 + 预算 + 模拟下单（待确认的模拟转账）。 */

const SCENARIO_DATE_FIELDS = [
  ["#scenario-date-year", 4],
  ["#scenario-date-month", 2],
  ["#scenario-date-day", 2],
];

function scenarioDateSegments() {
  return SCENARIO_DATE_FIELDS.map(([id]) => $(id)?.value.trim() || "");
}

function formatScenarioDateField(input, index) {
  input.value = input.value.replace(/\D/g, "").slice(0, SCENARIO_DATE_FIELDS[index][1]);
  if (
    input.value.length === SCENARIO_DATE_FIELDS[index][1] &&
    index < SCENARIO_DATE_FIELDS.length - 1
  )
    $(SCENARIO_DATE_FIELDS[index + 1][0]).focus();
}

function readScenarioDate() {
  const [year, month, day] = scenarioDateSegments();
  if (!year || !month || !day) return null;
  const value = `${year}-${month}-${day}`;
  const probe = new Date(`${value}T00:00:00Z`);
  if (
    Number.isNaN(probe.getTime()) ||
    probe.getUTCFullYear() !== Number(year) ||
    probe.getUTCMonth() !== Number(month) - 1 ||
    probe.getUTCDate() !== Number(day)
  )
    return null;
  return value;
}

function focusScenarioField(node, message) {
  bankMessage(message, true);
  node.focus();
  node.scrollIntoView({ block: "center", behavior: "smooth" });
}

function renderScenarioOptions() {
  for (const [id, items, label] of [
    [
      "#scenario-source",
      state.accounts,
      (account) => `${account.name} · 尾号 ${account.suffix}`,
    ],
    ["#scenario-payee", state.payees, (payee) => payeeLabel(payee)],
  ]) {
    const select = $(id);
    if (!select) continue;
    const selected = select.value;
    select.replaceChildren(new Option("请选择", ""));
    for (const item of items) select.add(new Option(label(item), item.id));
    select.value = selected;
  }
}

function renderScenarios() {
  const list = $("#scenarios-list");
  if (!list) return;
  list.replaceChildren();
  const scenarios = state.scenarios || [];
  if (!scenarios.length) {
    list.append(element("p", "muted", "暂无跨场景计划。"));
    return;
  }
  for (const plan of scenarios) {
    const row = element("article", "operation-card");
    row.append(
      element("strong", "", plan.title),
      element(
        "p",
        "",
        `${plan.kind === "birthday" ? "生日计划" : plan.kind === "anniversary" ? "纪念日计划" : "自定义场景"} · ${plan.occasion_date} · 预算 ${currency(plan.budget_minor)}`,
      ),
      element(
        "p",
        "field-help",
        plan.status === "ordered"
          ? "已生成待确认的模拟转账；请在操作记录或确认单中核对。"
          : plan.status === "cancelled"
            ? "计划已取消。"
            : plan.status === "expired"
              ? "日期已过；不会自动下单。"
              : `还有 ${plan.days_until} 天${plan.order_due ? " · 今天可在核对后模拟下单" : ""}。`,
      ),
    );
    if (plan.status === "active") {
      const actions = element("div", "card-actions");
      actions.append(
        scenarioButton("模拟下单", async () => {
          try {
            const result = await api(`/api/bank/scenarios/${plan.scenario_id}/order`, {
              method: "POST",
              body: "{}",
            });
            await loadBankData();
            bankMessage("已准备模拟转账；请核对确认单，批准前不会扣款。");
            openOperation(result.operation.id);
          } catch (error) {
            bankMessage(error.message, true);
          }
        }),
        scenarioButton("取消计划", async () => {
          try {
            await api(`/api/bank/scenarios/${plan.scenario_id}/cancel`, {
              method: "POST",
              body: "{}",
            });
            await loadBankData();
            bankMessage("计划已取消；不会发起转账。");
          } catch (error) {
            bankMessage(error.message, true);
          }
        }),
      );
      row.append(actions);
    }
    list.append(row);
  }
}

function scenarioButton(label, handler) {
  const button = element("button", "button secondary bank-action", label);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

function bindScenarioForm() {
  SCENARIO_DATE_FIELDS.forEach(([id, length], index) => {
    const input = $(id);
    input?.addEventListener("input", () => formatScenarioDateField(input, index));
    input?.addEventListener("blur", () => {
      if (input.value && input.value.length < length)
        input.value = input.value.padStart(length, "0");
    });
  });

  $("#scenario-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = $("#scenario-title").value.trim();
    if (!title) return focusScenarioField($("#scenario-title"), "请填写计划名称。");
    const date = readScenarioDate();
    if (!date) {
      const firstEmpty = SCENARIO_DATE_FIELDS.map(([id]) => $(id)).find(
        (input) => !input.value.trim(),
      );
      return focusScenarioField(
        firstEmpty || $("#scenario-date-year"),
        "请填写完整的日期（YYYY-MM-DD）。",
      );
    }
    const budgetText = $("#scenario-budget").value.trim();
    const budget = Math.round(Number(budgetText) * 100);
    if (!budgetText || !Number.isFinite(budget) || budget <= 0)
      return focusScenarioField($("#scenario-budget"), "请填写正确的预算金额。");
    if (!$("#scenario-source").value)
      return focusScenarioField($("#scenario-source"), "请选择付款账户。");
    if (!$("#scenario-payee").value)
      return focusScenarioField($("#scenario-payee"), "请选择模拟商户或收款人。");
    try {
      await api("/api/bank/scenarios", {
        method: "POST",
        body: JSON.stringify({
          kind: $("#scenario-kind").value,
          title,
          occasion_date: date,
          budget_minor: budget,
          source_id: $("#scenario-source").value,
          payee_id: $("#scenario-payee").value,
        }),
      });
      event.target.reset();
      await loadBankData();
      bankMessage("跨场景计划已保存；临近日期时可模拟下单，仍需独立确认。");
    } catch (error) {
      bankMessage(error.message, true);
    }
  });
}

bindScenarioForm();
