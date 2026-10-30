"use strict";

Object.assign(state, {
  workflowPlan: null,
  workflowDraft: null,
  workflowPreview: null,
  workflowRequest: null,
  planRevision: 0,
  editingPayee: null,
});
Object.assign(errors, {
  INVALID_PAYEE_QUERY: "请填写姓名、备注或账户尾号。",
  INVALID_PLAN: "请选定 1–5 个不同的已登记订阅。",
  PLAN_EVIDENCE_CHANGED: "账户、收款人或订阅信息已变化，请重新查看并核对方案。",
  PLAN_REQUEST_CONFLICT: "原方案请求的内容不一致，请先核对原方案。",
  PLAN_PARAMETERS_CONFLICT:
    "操作不符合已选方案的对象、金额或顺序，未创建新操作。",
  PLAN_STEP_BLOCKED: "原方案还有未成功的步骤，后续操作已停止。",
  PLAN_ALREADY_COMPLETED: "方案已完成，不会追加新操作。",
});

function invalidateWorkflowPreview() {
  state.planRevision += 1;
  state.workflowDraft = null;
  state.workflowPreview = null;
  state.workflowRequest = null;
  $("#workflow-preview").replaceChildren();
  $("#workflow-acknowledged").checked = false;
  $("#workflow-acknowledged").disabled = true;
  $("#workflow-create").disabled = true;
}

function resetTransfers() {
  state.workflowPlan = null;
  state.editingPayee = null;
  invalidateWorkflowPreview();
  $("#payee-note-dialog").close();
  $("#payee-note-form").reset();
  $("#demo-contacts-form").reset();
  $("#workflow-form").reset();
  $("#contact-search").value = "";
  $("#contacts-list").replaceChildren();
  $("#workflow-subscriptions").replaceChildren();
}

function renderContacts() {
  const target = $("#contacts-list"),
    query = $("#contact-search").value.normalize("NFKC").trim().toLowerCase();
  target.replaceChildren();
  const matches = state.payees.filter((p) =>
    `${p.name} ${p.note} ${p.suffix}`
      .normalize("NFKC")
      .toLowerCase()
      .includes(query),
  );
  for (const payee of matches) {
    const card = element("article", "operation-card contact-card");
    const body = element("div");
    body.append(
      element("strong", "", payee.name),
      element(
        "p",
        "muted",
        `${payee.kind === "self" ? "本人账户" : payee.kind === "demo" ? "虚构联系人" : "已登记收款人"} · ${payee.bank_name} · 尾号 ${payee.suffix}`,
      ),
      element("p", "", payee.note || "未设置备注"),
    );
    const actions = element("div", "bank-actions");
    actions.append(
      bankButton("向此账户转账", () => {
        $("#transfer-payee").value = payee.id;
        $("#transfer-form").scrollIntoView({ block: "center" });
        $("#transfer-amount").focus();
        bankMessage(`已选择 ${payeeLabel(payee)}，尚未准备或执行转账。`);
      }),
      bankButton("编辑备注", () => {
        state.editingPayee = payee;
        $("#payee-note-identity").textContent =
          `${payee.name} · 模拟银行 · 尾号 ${payee.suffix}`;
        $("#payee-note").value = payee.note;
        $("#payee-note-password").value = "";
        $("#payee-note-error").textContent = "";
        $("#payee-note-dialog").showModal();
      }),
    );
    card.append(body, actions);
    target.append(card);
  }
  if (!matches.length)
    target.append(
      element(
        "p",
        "muted",
        "没有匹配的已登记收款人。可以载入下方虚构联系人用于演示。",
      ),
    );
  if (matches.filter((p) => p.kind !== "self").length > 1 && query)
    target.prepend(
      element(
        "p",
        "field-help",
        "有多个匹配，请按备注和尾号核对，不能只凭姓名选人。",
      ),
    );
}

function renderWorkflowOptions() {
  for (const [selector, items, label] of [
    ["#workflow-source", state.accounts, (a) => `${a.name} · 尾号 ${a.suffix}`],
    ["#workflow-payee", state.payees, payeeLabel],
  ]) {
    const selected = $(selector).value;
    $(selector).replaceChildren(new Option("请选择", ""));
    for (const item of items) $(selector).add(new Option(label(item), item.id));
    $(selector).value = selected;
  }
  const selected = new Set(
    [...$("#workflow-subscriptions").querySelectorAll("input:checked")].map(
      (node) => node.value,
    ),
  );
  const target = $("#workflow-subscriptions");
  target.replaceChildren();
  const subscriptions = state.subscriptions.filter(
    (s) =>
      s.account_id === $("#workflow-source").value && s.status === "active",
  );
  for (const subscription of subscriptions) {
    const row = element("label", "check-row"),
      input = element("input");
    input.type = "checkbox";
    input.value = subscription.id;
    input.checked = selected.has(subscription.id);
    row.append(
      input,
      document.createTextNode(
        `${subscription.merchant} · ${currency(subscription.amount_minor)} / 登记期`,
      ),
    );
    target.append(row);
  }
  if (!subscriptions.length)
    target.append(
      element(
        "p",
        "muted",
        "先选扣费账户；仅能选择已登记且有效的订阅，疑似项须先核对登记。",
      ),
    );
}

function workflowPreviewContent(preview) {
  const content = element("div", "operation-card");
  content.append(element("h3", "", "核对方案与资金影响"));
  const steps = element("ol");
  for (const step of preview.steps) steps.append(element("li", "", step.label));
  const subscriptions = element("div");
  for (const subscription of preview.subscriptions)
    subscriptions.append(
      element(
        "p",
        "muted",
        `取消项：${subscription.merchant} · ${currency(subscription.amount_minor)} / 登记期`,
      ),
    );
  content.append(
    steps,
    subscriptions,
    element(
      "p",
      "",
      `付款：${preview.source.name} · 尾号 ${preview.source.suffix}`,
    ),
    element("p", "", `收款：${payeeLabel(preview.recipient)}`),
    element(
      "p",
      "",
      `本次转账 ${currency(preview.transfer_minor)} · 当前余额 ${currency(preview.current_balance_minor)} · 预计剩余 ${currency(preview.estimated_balance_minor)}`,
    ),
    element(
      "p",
      "",
      `取消项每登记期预计合计少支出 ${currency(preview.future_reduction_per_cycle_minor)}，不代表本次到账。`,
    ),
    element("p", "muted", preview.note),
  );
  return content;
}

function renderWorkflowPlan() {
  $("#chat-log")
    .querySelectorAll(".workflow-plan-summary")
    .forEach((node) => node.remove());
  const plan = state.workflowPlan;
  if (!plan) return;
  const card = element("section", "workflow-plan-summary operation-card");
  card.setAttribute("aria-label", "已选方案进度");
  const stopped = plan.steps.some((s) =>
    ["rejected", "failed", "expired", "outcome_unknown"].includes(s.state),
  );
  card.append(
    element(
      "h3",
      "",
      plan.completed
        ? "方案已完成"
        : stopped
          ? "方案已停止，先核对原操作"
          : "已选方案",
    ),
  );
  const steps = element("ol");
  for (const step of plan.steps)
    steps.append(
      element(
        "li",
        "",
        `${step.label}${step.kind === "transfer" ? ` · ${currency(step.arguments.amount_minor)}` : ""} · ${step.state === "not_started" ? "未开始" : BANK_STATES[step.state] || step.state}`,
      ),
    );
  card.append(
    steps,
    element(
      "p",
      "field-help",
      `此方案不授予付款权限；${state.executionPolicy?.mode === "PREAUTHORIZED" ? "当前使用你选择的预授权" : "当前逐笔人工确认"}。已完成步骤不会重做。`,
    ),
  );
  const awaitingAction = plan.steps.some((step) =>
    ["awaiting_confirmation", "authorized", "executing"].includes(step.state),
  );
  if (!plan.completed && !stopped && !awaitingAction) {
    const button = element(
      "button",
      "button secondary",
      "将此方案交给助手核对",
    );
    button.type = "button";
    button.disabled = state.health?.agent_mode !== "model";
    button.addEventListener("click", () => {
      if (state.sending || state.bankBusy || !state.workflowReady) return;
      $("#chat-input").value =
        "请先核对我在界面选定的订阅整理与转账方案，按约定的顺序、对象和金额处理未完成步骤；每次操作遵守当前执行方式，已完成步骤只回查，不重做。";
      $("#chat-form").requestSubmit();
    });
    card.append(button);
    if (state.health?.agent_mode !== "model")
      card.append(
        element(
          "p",
          "muted",
          "当前为离线演示，方案已保存；需要模型模式才能由助手规划调用。",
        ),
      );
  }
  $("#chat-log").append(card);
}

$("#contact-search").addEventListener("input", () => {
  renderContacts();
  updateBankButtons();
});
$("#demo-contacts-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const password = $("#demo-contacts-password").value;
  $("#demo-contacts-password").value = "";
  runBank(async (user) => {
    await api("/api/bank/payees/demo", {
      method: "POST",
      body: JSON.stringify({ password }),
    });
    if (state.user !== user) return;
    await loadBankData();
    bankMessage(
      "已载入虚构联系人；未扣款、未创建授权。请留意两位同名张明的备注和尾号。",
    );
  });
});
$("#payee-note-close").addEventListener("click", () => {
  if (!state.bankBusy) $("#payee-note-dialog").close();
});
$("#payee-note-dialog").addEventListener("cancel", (event) => {
  if (state.bankBusy) event.preventDefault();
});
$("#payee-note-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state.editingPayee) return;
  const id = state.editingPayee.id,
    note = $("#payee-note").value,
    password = $("#payee-note-password").value;
  $("#payee-note-password").value = "";
  runBank(async (user) => {
    try {
      await api(`/api/bank/payees/${id}/note`, {
        method: "POST",
        body: JSON.stringify({ note, password }),
      });
      if (state.user !== user) return;
      $("#payee-note-dialog").close();
      await loadBankData();
      bankMessage("备注已更新，收款账户不变，未产生转账或授权。");
    } catch (error) {
      if (state.user === user)
        $("#payee-note-error").textContent = error.message;
    }
  });
});
$("#workflow-form").addEventListener("input", invalidateWorkflowPreview);
$("#workflow-source").addEventListener("change", renderWorkflowOptions);
$("#workflow-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runBank(async (user) => {
    normalizeAmount("#workflow-amount");
    const draft = {
      source_id: $("#workflow-source").value,
      payee_id: $("#workflow-payee").value,
      amount_minor: bankAmount("#workflow-amount"),
      subscription_ids: [
        ...$("#workflow-subscriptions").querySelectorAll("input:checked"),
      ].map((node) => node.value),
    };
    if (!draft.subscription_ids.length || draft.subscription_ids.length > 5)
      throw new Error(errors.INVALID_PLAN);
    invalidateWorkflowPreview();
    const revision = state.planRevision;
    const preview = await api("/api/bank/plans/preview", {
      method: "POST",
      body: JSON.stringify(draft),
    });
    if (state.user !== user || revision !== state.planRevision) return;
    state.workflowDraft = draft;
    state.workflowPreview = preview;
    state.workflowRequest = crypto.randomUUID();
    $("#workflow-preview").replaceChildren(workflowPreviewContent(preview));
    $("#workflow-acknowledged").disabled = false;
  });
});
$("#workflow-acknowledged").addEventListener("change", () => {
  $("#workflow-create").disabled =
    !$("#workflow-acknowledged").checked || !state.workflowPreview;
});
$("#workflow-create").addEventListener("click", () => {
  if (!state.workflowPreview || !$("#workflow-acknowledged").checked) return;
  const values = {
    ...state.workflowDraft,
    request_id: state.workflowRequest,
    evidence_digest: state.workflowPreview.evidence_digest,
    acknowledged: true,
  };
  runBank(async (user) => {
    const plan = await api("/api/bank/plans", {
      method: "POST",
      body: JSON.stringify(values),
    });
    if (state.user !== user) return;
    state.conversation = plan.conversation_id;
    state.workflowPlan = plan;
    state.executionPolicy = null;
    state.operationTask = null;
    welcome();
    await loadBankData();
    invalidateWorkflowPreview();
    setPage("assistant");
    addMessage(
      "application-note",
      "已保存你选定的方案，尚未执行。核对方案后，可点击“将此方案交给助手核对”。每笔操作仍需独立确认或你明确选择的预授权。",
    );
  });
});
