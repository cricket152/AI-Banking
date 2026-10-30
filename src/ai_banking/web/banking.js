"use strict";

Object.assign(state, {
  payees: [],
  subscriptions: [],
  operations: [],
  grants: [],
  operationTask: null,
  executionPolicy: null,
  policyBusy: false,
  bankBusy: false,
  workflowReady: false,
  workflowRevision: 0,
  confirmation: null,
  transferDraft: null,
  uncertainOperations: new Set(),
});

Object.assign(errors, {
  BANK_SETUP_REQUIRED: "银行业务尚未就绪，请联系本地管理员。",
  INSUFFICIENT_BALANCE: "可用余额不足，或不满足最低保留余额。",
  INVALID_TRANSFER: "付款账户与收款账户必须不同，且币种一致。",
  STEP_PARAMETERS_CONFLICT:
    "原任务还有待处理或未成功的操作，请先核对原操作。不会创建新的付款。",
  SINGLE_LIMIT_EXCEEDED: "超过预授权单笔上限，未执行。",
  GRANT_EXHAUSTED: "累计授权额度不足，未执行。",
  GRANT_INVALID: "授权已失效或撤销，未执行。",
  GRANT_EXPIRED: "授权已过期，未执行。",
  POLICY_REJECTED: "操作不在所选授权范围内，未执行。",
  ACTIVE_GRANT_EXISTS: "该付款账户已有有效授权，请先核对并撤销旧授权。",
  INVALID_POLICY: "请检查授权范围、额度和有效期。",
  OPERATION_NOT_AUTHORIZED: "操作尚未获得有效授权。",
  OPERATION_NOT_CONFIRMABLE: "操作已过期或不能确认，请刷新原操作。",
  NOT_AWAITING_CONFIRMATION: "操作已不处于待确认状态，请刷新。",
  APPROVAL_PROOF_REJECTED: "确认凭证已失效，请重新打开原操作确认单。",
  OUTCOME_UNKNOWN: "结果待核实，请核实原操作，不要重新付款。",
  RESULT_UNAVAILABLE: "暂未取得回执，请查询原操作，不要重新付款。",
  ACCOUNT_OUTCOME_UNKNOWN: "该账户存在结果待核实的操作，已暂停新操作。",
  GRANT_OUTCOME_UNKNOWN: "该授权存在结果待核实的操作，已暂停新操作。",
  RESOURCE_NOT_FOUND: "操作或资源不存在，或不属于当前用户。",
  OPERATION_NOT_SUCCEEDED: "原操作尚未成功，不能继续任务。",
  TASK_PAUSED:
    "本任务因授权或资金检查失败已暂停。请核对原因，必要时在界面重新选择策略后再继续。",
});

const BANK_STATES = {
  awaiting_confirmation: "待确认",
  authorized: "已授权，待执行",
  executing: "执行中",
  succeeded: "已完成",
  failed: "失败",
  rejected: "已拒绝",
  expired: "已过期",
  outcome_unknown: "结果待核实",
};

function bankMoney(minor) {
  return `¥${Math.floor(minor / 100).toLocaleString("zh-CN")}.${String(minor % 100).padStart(2, "0")}`;
}

function bankAmount(id, zeroAllowed = false) {
  const value = $(id).value.trim();
  if (!/^\d{1,11}(\.\d{1,2})?$/.test(value))
    throw new Error("金额须为非负数字，最多两位小数。");
  const [whole, decimal = ""] = value.split(".");
  const minor = Number(whole) * 100 + Number(decimal.padEnd(2, "0"));
  if (
    !Number.isSafeInteger(minor) ||
    minor > 1000000000000 ||
    (!zeroAllowed && minor === 0)
  ) {
    throw new Error("金额超出允许范围；转账金额必须大于零。");
  }
  return minor;
}

function buildGrantValues() {
  const allowed = [];
  if ($("#grant-transfer").checked) allowed.push("transfer");
  if ($("#grant-cancel").checked) allowed.push("cancel_subscription");
  if (!allowed.length) throw new Error("请明确选择至少一种允许的操作。");
  const sourceId = $("#grant-source").value;
  if (!sourceId) throw new Error("请选择付款账户。");
  const payeeIds = [
    ...$("#grant-payees").querySelectorAll("input:checked"),
  ].map((node) => node.value);
  const subscriptionIds = [
    ...$("#grant-subscriptions").querySelectorAll("input:checked"),
  ].map((node) => node.value);
  if (allowed.includes("transfer") && !payeeIds.length)
    throw new Error("请选择至少一个允许的收款账户。");
  if (allowed.includes("cancel_subscription") && !subscriptionIds.length)
    throw new Error("请选择至少一个允许取消的订阅。");
  normalizeGrantAmounts();
  const limitMinor = bankAmount("#grant-limit", true);
  const singleMinor = bankAmount("#grant-single", true);
  const minimumMinor = bankAmount("#grant-minimum", true);
  if (allowed.includes("transfer") && (limitMinor <= 0 || singleMinor <= 0))
    throw new Error("允许转账时，累计与单笔上限必须大于 0。");
  if (singleMinor > limitMinor)
    throw new Error("单笔上限不能超过累计支出上限。");
  const segments = expirySegments();
  if (segments.some((value) => !value))
    throw new Error("请填写完整的截止时间（东八区 UTC+8）。");
  const expiresAt = readExpiryValue();
  if (expiresAt === null) throw new Error("截止时间无效，请检查年月日时分。");
  if (expiresAt <= Date.now() / 1000)
    throw new Error("截止时间必须晚于当前时间（东八区 UTC+8）。");
  return {
    request_id: crypto.randomUUID(),
    source_id: sourceId,
    currency: "CNY",
    payee_ids: allowed.includes("transfer") ? payeeIds : [],
    subscription_ids: allowed.includes("cancel_subscription")
      ? subscriptionIds
      : [],
    allowed_operations: allowed,
    limit_minor: limitMinor,
    single_minor: singleMinor,
    minimum_minor: minimumMinor,
    expires_at: expiresAt,
    password: $("#grant-password").value,
  };
}

function bankMessage(text, error = false) {
  $("#bank-message").textContent = text;
  $("#bank-message").classList.toggle("error", error);
}

function bankButton(label, action, variant = "secondary") {
  const button = element("button", `button ${variant} bank-action`, label);
  button.type = "button";
  button.addEventListener("click", () => runBank(action));
  return button;
}

function updateBankButtons() {
  const busy =
    !state.user ||
    state.bankBusy ||
    state.sending ||
    state.policyBusy ||
    !state.workflowReady ||
    !state.health?.bank_ready;
  document
    .querySelectorAll(".bank-action, #transfer-submit, #grant-submit")
    .forEach((b) => {
      b.disabled = busy;
    });
  $("#operation-approve").disabled =
    state.bankBusy ||
    !state.confirmation ||
    !$("#operation-acknowledged").checked;
  $("#operation-reject").disabled = state.bankBusy || !state.confirmation;
  $("#operation-dialog-close").disabled = state.bankBusy;
  $("#operation-acknowledged").disabled = state.bankBusy;
  $("#agent-policy-mode").disabled = busy;
  $("#chat-send").disabled =
    !state.user || state.sending || state.bankBusy || !state.workflowReady;
  $("#new-chat").disabled =
    !state.user || state.sending || state.bankBusy || !state.workflowReady;
  $("#agent-policy-grant").disabled =
    busy || $("#agent-policy-mode").value !== "PREAUTHORIZED";
  const preauthorized = $("#agent-policy-mode").value === "PREAUTHORIZED";
  const createGrant = $("#agent-policy-create-grant");
  if (createGrant)
    createGrant.hidden = !(
      preauthorized && !state.grants.some((g) => g.status === "active")
    );
  const viewGrant = $("#agent-policy-view");
  if (viewGrant)
    viewGrant.hidden = !(preauthorized && $("#agent-policy-grant").value);
}

async function runBank(action) {
  if (!state.user || state.bankBusy || state.sending || !state.workflowReady)
    return;
  const user = state.user;
  state.bankBusy = true;
  bankMessage("");
  updateBankButtons();
  try {
    await action(user);
  } catch (error) {
    if (state.user === user) bankMessage(error.message, true);
  } finally {
    state.bankBusy = false;
    updateBankButtons();
  }
}

function resetBanking() {
  state.payees = [];
  state.subscriptions = [];
  resetInsights();
  resetTransfers();
  state.operations = [];
  state.grants = [];
  state.operationTask = null;
  state.executionPolicy = null;
  state.confirmation = null;
  state.transferDraft = null;
  state.workflowReady = false;
  state.workflowRevision += 1;
  state.uncertainOperations.clear();
  $("#operation-dialog").close();
  $("#transfer-form").reset();
  $("#grant-form").reset();
  grantError("");
  grantInfo("");
  updateGrantScopeState();
  for (const id of ["#subscriptions-list", "#operations-list", "#grants-list"])
    $(id).replaceChildren();
  bankMessage("");
}

function bankAccountLabel(id) {
  const own = state.accounts.find((a) => a.id === id);
  if (own) return `${own.name} · 尾号 ${own.suffix}`;
  const payee = state.payees.find((p) => p.account_id === id);
  return payee ? `${payee.name} · 尾号 ${payee.suffix}` : id || "—";
}

function payeeLabel(payee) {
  return `${payee.name}${payee.note ? `（${payee.note}）` : ""} · 模拟银行 · 尾号 ${payee.suffix}`;
}

function shanghaiTime(seconds) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(seconds * 1000));
}

function parseShanghaiTime(value) {
  const match = value
    .trim()
    .match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})$/);
  if (!match) return null;
  const [year, month, day, hour, minute] = match.slice(1).map(Number);
  const naive = Date.UTC(year, month - 1, day, hour, minute);
  const probe = new Date(naive);
  if (
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() !== month - 1 ||
    probe.getUTCDate() !== day ||
    probe.getUTCHours() !== hour ||
    probe.getUTCMinutes() !== minute
  )
    return null;
  return (naive - 8 * 3600 * 1000) / 1000;
}

function grantError(message) {
  const node = $("#grant-error");
  node.textContent = message || "";
  node.hidden = !message;
  if (message) node.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function grantInfo(message) {
  const node = $("#grant-info");
  if (!node) return;
  node.textContent = message || "";
  node.hidden = !message;
}

const EXPIRY_FIELDS = [
  ["#grant-expiry-year", 4],
  ["#grant-expiry-month", 2],
  ["#grant-expiry-day", 2],
  ["#grant-expiry-hour", 2],
  ["#grant-expiry-minute", 2],
];

function expirySegments() {
  return EXPIRY_FIELDS.map(([id]) => $(id).value.trim());
}

function setExpirySegments(seconds) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(seconds * 1000));
  const part = (type) => parts.find((item) => item.type === type)?.value || "";
  const values = [
    part("year"),
    part("month"),
    part("day"),
    part("hour"),
    part("minute"),
  ];
  EXPIRY_FIELDS.forEach(([id], index) => {
    $(id).value = values[index];
  });
}

function setDefaultGrantExpiry() {
  if (expirySegments().some((value) => value)) return;
  setExpirySegments(Date.now() / 1000 + 86400);
}

function formatExpiryField(input, index) {
  input.value = input.value
    .replace(/\D/g, "")
    .slice(0, EXPIRY_FIELDS[index][1]);
  if (
    input.value.length === EXPIRY_FIELDS[index][1] &&
    index < EXPIRY_FIELDS.length - 1
  )
    $(EXPIRY_FIELDS[index + 1][0]).focus();
}

function readExpiryValue() {
  const [year, month, day, hour, minute] = expirySegments();
  if (!year || !month || !day || !hour || !minute) return null;
  return parseShanghaiTime(`${year}-${month}-${day} ${hour}:${minute}`);
}

function fillGrantFormFromGrant(grant) {
  $("#grant-form").reset();
  $("#grant-source").value = grant.source_id;
  const operations = grant.scopes?.operations || [];
  $("#grant-transfer").checked = operations.includes("transfer");
  $("#grant-cancel").checked = operations.includes("cancel_subscription");
  updateGrantScopeState();
  for (const id of grant.payee_ids || []) {
    const node = document.querySelector(`#grant-payees input[value="${id}"]`);
    if (node) node.checked = true;
  }
  for (const id of grant.scopes?.subscription_ids || []) {
    const node = document.querySelector(
      `#grant-subscriptions input[value="${id}"]`,
    );
    if (node) node.checked = true;
  }
  updateMultiSummary("#grant-payees", "#grant-payees-summary");
  updateMultiSummary("#grant-subscriptions", "#grant-subscriptions-summary");
  $("#grant-limit").value = (grant.limit_minor / 100).toFixed(2);
  $("#grant-single").value = (grant.single_minor / 100).toFixed(2);
  $("#grant-minimum").value = (grant.minimum_minor / 100).toFixed(2);
  setExpirySegments(grant.expires_at);
  grantError("");
  grantInfo(
    "已载入当前授权信息；如需新建，请修改范围与额度并重新输入登录密码。",
  );
}

function normalizeAmount(id) {
  const input = $(id);
  if (!input) return;
  const raw = input.value.trim().replace(/[,，\s¥￥]/g, "");
  if (!raw) return;
  const number = Number(raw);
  if (!Number.isFinite(number)) return;
  input.value = (Math.round(number * 100) / 100).toFixed(2);
}

function normalizeGrantAmounts() {
  for (const id of ["#grant-limit", "#grant-single", "#grant-minimum"])
    normalizeAmount(id);
}

function updateMultiSummary(listId, summaryId) {
  const count = $(listId).querySelectorAll("input:checked").length;
  $(summaryId).textContent = count ? `已选 ${count} 项` : "未选择";
}

function updateGrantScopeState() {
  for (const [enabled, boxId, listId, summaryId] of [
    [
      $("#grant-transfer").checked,
      "#grant-payees-select",
      "#grant-payees",
      "#grant-payees-summary",
    ],
    [
      $("#grant-cancel").checked,
      "#grant-subscriptions-select",
      "#grant-subscriptions",
      "#grant-subscriptions-summary",
    ],
  ]) {
    const box = $(boxId);
    box.dataset.disabled = enabled ? "false" : "true";
    if (!enabled) {
      box.open = false;
      $(listId)
        .querySelectorAll("input")
        .forEach((node) => {
          node.checked = false;
        });
    }
    updateMultiSummary(listId, summaryId);
  }
}

function renderBankOptions() {
  for (const id of ["#transfer-source", "#grant-source"]) {
    const selected = $(id).value;
    $(id).replaceChildren(new Option("请选择付款账户", ""));
    for (const a of state.accounts)
      $(id).add(
        new Option(
          `${a.name} · ${a.suffix} · ${currency(a.balance_minor)}`,
          a.id,
        ),
      );
    $(id).value = selected;
  }
  const selectedPayee = $("#transfer-payee").value;
  $("#transfer-payee").replaceChildren(new Option("请选择收款人", ""));
  for (const p of state.payees)
    $("#transfer-payee").add(new Option(payeeLabel(p), p.id));
  $("#transfer-payee").value = selectedPayee;
  for (const [id, items, label] of [
    ["#grant-payees", state.payees, (p) => payeeLabel(p)],
    [
      "#grant-subscriptions",
      state.subscriptions.filter((s) => s.status === "active"),
      (s) => `${s.merchant} · ${bankAccountLabel(s.account_id)}`,
    ],
  ]) {
    const selected = new Set(
      [...$(id).querySelectorAll("input:checked")].map((n) => n.value),
    );
    $(id).replaceChildren();
    for (const item of items) {
      const row = element("label", "check-row");
      const input = element("input");
      input.type = "checkbox";
      input.value = item.id;
      input.checked = selected.has(item.id);
      row.append(input, document.createTextNode(label(item)));
      $(id).append(row);
    }
  }
  updateGrantScopeState();
  setDefaultGrantExpiry();
}

function renderPolicy() {
  const policy = state.executionPolicy || {
    mode: "HUMAN_APPROVAL",
    grant_id: null,
  };
  $("#agent-policy-mode").value = policy.mode;
  $("#agent-policy-grant").replaceChildren(new Option("请选择有效预授权", ""));
  for (const g of state.grants.filter((g) => g.status === "active")) {
    $("#agent-policy-grant").add(
      new Option(
        `${bankAccountLabel(g.source_id)} · 剩余 ${currency(g.remaining_minor)}`,
        g.id,
      ),
    );
  }
  if (
    policy.grant_id &&
    !state.grants.some((g) => g.id === policy.grant_id && g.status === "active")
  ) {
    $("#agent-policy-grant").add(
      new Option("原授权已失效，执行已受限", policy.grant_id),
    );
  }
  $("#agent-policy-grant").value = policy.grant_id || "";
  const activeGrant = state.grants.find(
    (g) => g.id === policy.grant_id && g.status === "active",
  );
  const safetyHelp = $("#agent-safety-help");
  if (safetyHelp) {
    const safetyText =
      policy.mode === "PREAUTHORIZED"
        ? "指定预授权 · 每笔仍由后端复核范围与额度"
        : "默认逐笔确认 · 聊天文字不代替授权";
    safetyHelp.dataset.tooltip = safetyText;
    safetyHelp.setAttribute("aria-label", safetyText);
  }
  updatePolicyStatusText(activeGrant);
  updatePolicySummary();
  if (policy.mode === "PREAUTHORIZED" && !activeGrant) {
    const panel = $("#agent-policy-panel");
    if (panel) panel.open = true;
  }
}

function currentActiveGrant() {
  const grantId = $("#agent-policy-grant").value;
  return state.grants.find((g) => g.id === grantId && g.status === "active");
}

function updatePolicyStatusText(activeGrant = currentActiveGrant()) {
  const status = $("#agent-policy-status");
  if (!status) return;
  let message = "";
  if (!state.workflowReady) {
    message = "正在核对本对话执行策略，恢复完成前不能发起操作。";
  } else if ($("#agent-policy-mode").value === "PREAUTHORIZED") {
    message = activeGrant
      ? "本对话使用所选授权；超范围、超额度或失效时停止执行。"
      : "尚无有效预授权：请先在业务办理创建授权，再回到这里选择并应用。";
  }
  status.textContent = message;
  status.hidden = !message;
}

function updatePolicySummary() {
  const summary = $("#agent-policy-summary");
  if (!summary) return;
  if (!state.workflowReady) {
    summary.textContent = "恢复中…";
  } else if ($("#agent-policy-mode").value === "PREAUTHORIZED") {
    summary.textContent = currentActiveGrant()
      ? "预授权模式"
      : "预授权 · 授权待选择";
  } else {
    summary.textContent = "每笔人工确认";
  }
}

async function applyConversationPolicy() {
  const conversation = state.conversation;
  if (!conversation || state.policyBusy) return;
  const mode = $("#agent-policy-mode").value;
  const grantId =
    mode === "PREAUTHORIZED" ? $("#agent-policy-grant").value : null;
  if (mode === "PREAUTHORIZED" && !grantId) {
    updatePolicyStatusText();
    updatePolicySummary();
    return;
  }
  state.policyBusy = true;
  updateBankButtons();
  try {
    const policy = await api(`/api/conversations/${conversation}/policy`, {
      method: "POST",
      body: JSON.stringify({ mode, grant_id: grantId }),
    });
    if (state.conversation !== conversation) return;
    state.executionPolicy = policy;
    await loadBankData();
  } catch (error) {
    const status = $("#agent-policy-status");
    if (status) {
      status.textContent = error.message;
      status.hidden = false;
    }
  } finally {
    state.policyBusy = false;
    updateBankButtons();
  }
}

function renderOperation(op, compact = false) {
  const card = element("article", "operation-card");
  card.dataset.operationId = op.id;
  const top = element("div", "operation-heading");
  const label = op.kind === "transfer" ? "模拟转账" : "取消订阅";
  const uncertain = state.uncertainOperations.has(op.id);
  top.append(
    element("strong", "", label),
    element(
      "span",
      `operation-state state-${op.state}`,
      uncertain ? "回执待核实" : BANK_STATES[op.state] || op.state,
    ),
  );
  card.append(top);
  if (op.kind === "transfer") {
    card.append(element("p", "operation-amount", currency(op.amount_minor)));
    card.append(
      element(
        "p",
        "",
        `${bankAccountLabel(op.source_id)} → ${bankAccountLabel(op.target_id)}`,
      ),
    );
  } else {
    const subscription = state.subscriptions.find(
      (s) => s.id === op.subscription_id,
    );
    card.append(element("p", "", subscription?.merchant || op.subscription_id));
  }
  card.append(
    element(
      "p",
      "field-help",
      `${op.mode === "PREAUTHORIZED" ? "预授权模式" : "人工确认"}`,
    ),
  );
  if (op.error_code)
    card.append(element("p", "error", errors[op.error_code] || op.error_code));
  const actions = element("div", "bank-actions");
  if (op.state === "awaiting_confirmation" && !uncertain)
    actions.append(
      bankButton("核对并处理", () => openOperation(op.id), "primary"),
    );
  if (op.state === "outcome_unknown")
    actions.append(
      bankButton("核实原操作", () => inspectOperation(op.id, true)),
    );
  actions.append(bankButton("刷新状态", () => inspectOperation(op.id)));
  if (
    compact &&
    op.state === "succeeded" &&
    state.health.agent_mode === "model"
  ) {
    actions.append(bankButton("继续／核对任务", () => resumeAgentTask(op.id)));
  }
  card.append(actions);
  return card;
}

function renderAgentOperations() {
  renderWorkflowPlan();
  $("#chat-log")
    .querySelectorAll(".agent-operation-list")
    .forEach((n) => n.remove());
  if (
    !state.operationTask ||
    (!state.operationTask.steps.length && !state.operationTask.pause_reason)
  )
    return;
  const group = element("section", "agent-operation-list");
  group.setAttribute("aria-label", "后端任务状态");
  const steps = state.operationTask.steps;
  const stopped = steps.some((s) =>
    ["rejected", "expired", "failed"].includes(s.state),
  );
  const progressTitle = state.operationTask.pause_reason
    ? "任务已暂停"
    : stopped
      ? "任务已停止"
      : "任务进度";
  group.append(
    element(
      "h3",
      "",
      steps.length
        ? `${progressTitle} · 已完成 ${steps.filter((s) => s.state === "succeeded").length}/${state.workflowPlan?.steps.length || steps.length} 步`
        : progressTitle,
    ),
  );
  group.append(
    element("p", "field-help", "以下为后端操作记录，模型文案不作为资金回执。"),
  );
  if (stopped)
    group.append(
      element(
        "p",
        "error",
        "存在拒绝、过期或失败的步骤；不会自动重做。新业务请新建对话。",
      ),
    );
  if (state.operationTask.pause_reason)
    group.append(
      element(
        "p",
        "error",
        `任务已暂停：${errors[state.operationTask.pause_reason] || state.operationTask.pause_reason}`,
      ),
    );
  for (const step of steps) {
    const operation = state.operations.find((o) => o.id === step.id);
    if (operation) group.append(renderOperation(operation, true));
  }
  $("#chat-log").append(group);
}

function renderBanking() {
  $("#bank-unavailable").hidden = !!state.health?.bank_ready;
  renderBankOptions();
  renderPolicy();
  renderContacts();
  renderWorkflowOptions();
  if (typeof renderCardOptions === "function") renderCardOptions();
  if (typeof renderCards === "function") renderCards();
  if (typeof renderScenarioOptions === "function") renderScenarioOptions();
  if (typeof renderScenarios === "function") renderScenarios();
  $("#subscriptions-list").replaceChildren();
  for (const s of state.subscriptions) {
    const row = element("article", "operation-card");
    row.append(
      element("strong", "", s.merchant),
      element(
        "p",
        "",
        `${currency(s.amount_minor)} / 期 · ${s.status === "active" ? "有效" : "已取消"}`,
      ),
    );
    row.append(
      element(
        "p",
        "field-help",
        `${s.source === "inferred_confirmed" ? "流水推断后经你确认 · 预计下次日期" : "下次登记扣费"}：${new Date(s.next_charge_at).toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai" })}${s.renewal_due_soon ? " · 近期提醒" : ""}`,
      ),
    );
    if (s.status === "active")
      row.append(bankButton("申请取消订阅", () => prepareCancellation(s)));
    $("#subscriptions-list").append(row);
  }
  if (!state.subscriptions.length)
    $("#subscriptions-list").append(element("p", "muted", "暂无登记订阅。"));
  renderSubscriptionCandidates();
  $("#operations-list").replaceChildren(
    ...state.operations.slice(0, 50).map((o) => renderOperation(o)),
  );
  if (!state.operations.length)
    $("#operations-list").append(element("p", "muted", "暂无操作记录。"));
  $("#grants-list").replaceChildren();
  for (const g of state.grants) {
    const card = element("article", "operation-card grant-card");
    card.dataset.grantId = g.id;
    card.append(
      element(
        "strong",
        "",
        `${bankAccountLabel(g.source_id)} · ${{ active: "有效授权", revoked: "已撤销", expired: "已过期", invalidated: "身份变更已失效" }[g.status] || g.status}`,
      ),
    );
    card.append(
      element(
        "p",
        "",
        `累计上限 ${currency(g.limit_minor)} · 单笔 ${currency(g.single_minor)} · 最低余额 ${currency(g.minimum_minor)}`,
      ),
    );
    card.append(
      element(
        "p",
        "",
        `已用 ${currency(g.spent_minor)} · 预占 ${currency(g.reserved_minor)} · 剩余 ${currency(g.remaining_minor)}`,
      ),
    );
    const payees = g.payee_ids
      .map((id) => state.payees.find((p) => p.id === id))
      .filter(Boolean)
      .map((p) => payeeLabel(p));
    const subscriptions = g.scopes.subscription_ids.map(
      (id) => state.subscriptions.find((s) => s.id === id)?.merchant || id,
    );
    card.append(
      element(
        "p",
        "field-help",
        `收款范围：${payees.join("、") || "无"}；订阅范围：${subscriptions.join("、") || "无"}；截止 ${shanghaiTime(g.expires_at)}（UTC+8）`,
      ),
    );
    if (g.status === "active")
      card.append(
        bankButton("在本对话启用", async () => {
          const conversation = state.conversation;
          if (!conversation) throw new Error("请先在 AI 助手创建对话。");
          const policy = await api(
            `/api/conversations/${conversation}/policy`,
            {
              method: "POST",
              body: JSON.stringify({
                mode: "PREAUTHORIZED",
                grant_id: g.id,
              }),
            },
          );
          state.executionPolicy = policy;
          await loadBankData();
          bankMessage("已在本对话启用该预授权；助手在范围内可自主执行。");
        }),
        bankButton("撤销这份授权", async () => {
          await api(`/api/bank/grants/${g.id}/revoke`, {
            method: "POST",
            body: "{}",
          });
          await loadBankData();
          bankMessage("授权已撤销；已完成的交易不会回滚。");
        }),
      );
    $("#grants-list").append(card);
  }
  renderAgentOperations();
  updateBankButtons();
}

async function loadBankData() {
  const revision = ++state.workflowRevision;
  state.workflowReady = false;
  updateBankButtons();
  if (!state.user || !state.health?.bank_ready) {
    state.workflowReady = !!state.user;
    renderBanking();
    return;
  }
  const user = state.user,
    conversation = state.conversation;
  const [payees, subscriptions, operations, grants, history, cards, scenarios] =
    await Promise.all([
      api("/api/bank/payees"),
      api("/api/bank/subscriptions"),
      api("/api/bank/operations"),
      api("/api/bank/grants"),
      conversation
        ? api(`/api/conversations/${conversation}`)
        : Promise.resolve(null),
      api("/api/bank/cards"),
      api("/api/bank/scenarios"),
    ]);
  if (state.user !== user || revision !== state.workflowRevision) return;
  state.payees = payees.payees;
  state.subscriptions = subscriptions.subscriptions;
  state.subscriptionCandidates = subscriptions.inferred_candidates;
  state.operations = operations.operations;
  state.grants = grants.grants;
  state.cards = cards.cards;
  state.scenarios = scenarios.scenarios;
  if (conversation === state.conversation && history) {
    state.operationTask = history.operation_task;
    state.executionPolicy = history.execution_policy;
    state.workflowPlan = history.workflow_plan;
    if (state.operationTask) {
      const taskOperations = await api(
        `/api/bank/operations?task_id=${state.operationTask.id}&limit=100`,
      );
      if (
        state.user !== user ||
        state.conversation !== conversation ||
        revision !== state.workflowRevision
      )
        return;
      const merged = new Map(
        [...state.operations, ...taskOperations.operations].map((o) => [
          o.id,
          o,
        ]),
      );
      state.operations = [...merged.values()].sort(
        (a, b) => b.created_at - a.created_at || b.id.localeCompare(a.id),
      );
    }
  }
  for (const op of state.operations) state.uncertainOperations.delete(op.id);
  state.workflowReady = true;
  renderBanking();
}

async function prepareCancellation(subscription) {
  const existing = state.operations.find(
    (o) =>
      o.kind === "cancel_subscription" &&
      o.subscription_id === subscription.id &&
      ["awaiting_confirmation", "outcome_unknown", "executing"].includes(
        o.state,
      ),
  );
  if (existing) {
    if (existing.state === "awaiting_confirmation")
      await openOperation(existing.id);
    else await inspectOperation(existing.id);
    return;
  }
  const task = await api("/api/bank/tasks", {
    method: "POST",
    body: JSON.stringify({ request_id: crypto.randomUUID() }),
  });
  const op = await api("/api/bank/subscriptions/cancel/prepare", {
    method: "POST",
    body: JSON.stringify({
      task_id: task.id,
      step_key: "cancel_1",
      source_id: subscription.account_id,
      subscription_id: subscription.id,
      currency: "CNY",
      mode: "HUMAN_APPROVAL",
      grant_id: null,
    }),
  });
  await loadBankData();
  await openOperation(op.id);
}

function appendSummary(label, value) {
  $("#operation-summary").append(
    element("dt", "", label),
    element("dd", "", String(value)),
  );
}

async function openOperation(id) {
  const user = state.user;
  const approval = await api(`/api/bank/operations/${id}/challenge`, {
    method: "POST",
    body: "{}",
  });
  if (state.user !== user) return;
  state.confirmation = { id, approval, user };
  const op = approval.summary;
  $("#operation-summary").replaceChildren();
  $("#operation-dialog-title").textContent =
    op.kind === "transfer" ? "核对转账" : "核对订阅取消";
  appendSummary(
    "付款 / 扣费账户",
    op.source_display
      ? `${op.source_display.name} · 尾号 ${op.source_display.suffix}`
      : bankAccountLabel(op.source_id),
  );
  if (op.kind === "transfer") {
    appendSummary(
      "收款账户",
      op.recipient
        ? `${op.recipient.name} · ${op.recipient.bank_name} · 尾号 ${op.recipient.suffix}`
        : bankAccountLabel(op.target_id),
    );
    if (op.recipient?.note)
      appendSummary("你设置的收款人备注", op.recipient.note);
    appendSummary("转账金额（CNY）", bankMoney(op.amount_minor));
    if (op.balance_before_minor !== undefined) {
      appendSummary(
        "当前余额预览（未预留）",
        currency(op.balance_before_minor),
      );
      appendSummary("转账后预计余额", currency(op.balance_after_minor));
    }
  } else {
    appendSummary(
      "订阅",
      state.subscriptions.find((s) => s.id === op.subscription_id)?.merchant ||
        "未知订阅",
    );
    appendSummary("资金影响", "不退款、不扣款");
  }
  appendSummary("费用", bankMoney(op.fee_minor));
  appendSummary("确认截止", `${shanghaiTime(op.expires_at)}（UTC+8）`);
  $("#operation-acknowledged").checked = false;
  $("#operation-dialog-error").textContent = "";
  $("#operation-approve").textContent =
    op.kind === "transfer"
      ? `确认转账 ${bankMoney(op.amount_minor)}`
      : "确认取消订阅";
  $("#operation-dialog").showModal();
  updateBankButtons();
}

async function inspectOperation(id, reconcile = false) {
  if (reconcile)
    await api(`/api/bank/operations/${id}/reconcile`, {
      method: "POST",
      body: "{}",
    });
  await api(`/api/bank/operations/${id}`);
  await Promise.all([loadData(), loadBankData()]);
  bankMessage("已查询原操作；未重新发起付款。");
}

async function decideOperation(decision) {
  const confirmation = state.confirmation;
  if (!confirmation || confirmation.user !== state.user) return;
  if (decision === "approve" && !$("#operation-acknowledged").checked) return;
  let result;
  try {
    result = await api(`/api/bank/operations/${confirmation.id}/decision`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        challenge: confirmation.approval.challenge,
        parameters_digest: confirmation.approval.summary.parameters_digest,
      }),
    });
  } catch (error) {
    if (state.user !== confirmation.user) return;
    state.uncertainOperations.add(confirmation.id);
    $("#operation-dialog-error").textContent =
      `${error.message} 请刷新原操作核实，不要新建付款。`;
    state.confirmation = null;
    try {
      await loadBankData();
    } catch {
      renderAgentOperations();
    }
    throw error;
  }
  if (state.user !== confirmation.user) return;
  state.confirmation = null;
  $("#operation-dialog").close();
  try {
    await Promise.all([loadData(), loadBankData()]);
  } catch {
    bankMessage("已取得操作回执，页面数据刷新失败，请点击刷新数据。", true);
    return;
  }
  bankMessage(`原操作${BANK_STATES[result.state] || result.state}。`);
  if (
    result.state === "succeeded" &&
    state.operationTask?.steps.some((s) => s.id === result.id)
  ) {
    await resumeAgentTask(result.id);
  }
}

async function resumeAgentTask(operationId) {
  if (
    state.sending ||
    state.health.agent_mode !== "model" ||
    !state.conversation
  )
    return;
  const user = state.user,
    conversation = state.conversation;
  state.sending = true;
  $("#chat-send").disabled = true;
  $("#new-chat").disabled = true;
  updateBankButtons();
  addMessage("application-note", "已处理独立确认，正在核对回执并继续原任务…");
  try {
    const result = await api(`/api/conversations/${conversation}/continue`, {
      method: "POST",
      body: JSON.stringify({ operation_id: operationId }),
    });
    if (state.user !== user || state.conversation !== conversation) return;
    if (result.cached)
      addMessage(
        "application-note",
        "此操作已续办，正在刷新当前后端状态；不会重复执行任务。",
      );
    else addMessage("assistant", result.answer, result.traces);
    await Promise.all([loadData(), loadBankData()]);
  } catch (error) {
    if (state.user === user && state.conversation === conversation) {
      addMessage(
        "error",
        `操作回执与对话继续分开处理。${error.message} 可查询原操作，或新发消息继续，系统不会自动重试。`,
      );
      try {
        await loadBankData();
      } catch {
        /* 保留已有后端回执，不伪装继续成功。 */
      }
    }
  } finally {
    state.sending = false;
    $("#chat-send").disabled = false;
    $("#new-chat").disabled = false;
    updateBankButtons();
  }
}

function initializeBanking() {
  $("#transfer-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runBank(async (user) => {
      normalizeAmount("#transfer-amount");
      const values = {
        source_id: $("#transfer-source").value,
        payee_id: $("#transfer-payee").value,
        amount_minor: bankAmount("#transfer-amount"),
        currency: "CNY",
        mode: "HUMAN_APPROVAL",
        grant_id: null,
      };
      if (!values.source_id || !values.payee_id)
        throw new Error("请明确选择付款账户和收款人。");
      const key = JSON.stringify(values);
      if (!state.transferDraft || state.transferDraft.key !== key)
        state.transferDraft = { key, requestId: crypto.randomUUID() };
      const draft = state.transferDraft;
      const task = await api("/api/bank/tasks", {
        method: "POST",
        body: JSON.stringify({ request_id: draft.requestId }),
      });
      const op = await api("/api/bank/transfers/prepare", {
        method: "POST",
        body: JSON.stringify({
          ...values,
          task_id: task.id,
          step_key: "manual_transfer_1",
        }),
      });
      if (state.user !== user) return;
      await loadBankData();
      if (op.state === "awaiting_confirmation") await openOperation(op.id);
      else
        bankMessage(
          `原操作${BANK_STATES[op.state] || op.state}；重复提交不会再次扣款。`,
        );
    });
  });
  $("#grant-form").addEventListener("submit", (event) => {
    event.preventDefault();
    grantError("");
    grantInfo("");
    let values;
    try {
      values = buildGrantValues();
    } catch (error) {
      grantError(error.message);
      return;
    }
    $("#grant-password").value = "";
    runBank(async (user) => {
      try {
        await api("/api/bank/grants", {
          method: "POST",
          body: JSON.stringify(values),
        });
      } catch (error) {
        grantError(error.message);
        return;
      } finally {
        delete values.password;
        $("#grant-password").value = "";
      }
      if (state.user !== user) return;
      $("#grant-form").reset();
      updateGrantScopeState();
      setDefaultGrantExpiry();
      grantError("");
      await loadBankData();
      bankMessage("预授权已创建。可在授权卡片点击“在本对话启用”。");
    });
  });
  EXPIRY_FIELDS.forEach(([id, length], index) => {
    const input = $(id);
    input?.addEventListener("input", () => formatExpiryField(input, index));
    input?.addEventListener("blur", () => {
      if (input.value && input.value.length < length)
        input.value = input.value.padStart(length, "0");
    });
  });
  for (const id of ["#grant-limit", "#grant-single", "#grant-minimum"]) {
    $(id)?.addEventListener("blur", () => normalizeAmount(id));
    $(id)?.addEventListener("change", () => normalizeAmount(id));
  }
  $("#transfer-amount")?.addEventListener("blur", () =>
    normalizeAmount("#transfer-amount"),
  );
  for (const id of ["#grant-transfer", "#grant-cancel"]) {
    $(id).addEventListener("change", updateGrantScopeState);
  }
  for (const [listId, summaryId] of [
    ["#grant-payees", "#grant-payees-summary"],
    ["#grant-subscriptions", "#grant-subscriptions-summary"],
  ]) {
    $(listId).addEventListener("change", () =>
      updateMultiSummary(listId, summaryId),
    );
  }
  document.addEventListener("click", (event) => {
    for (const box of document.querySelectorAll(".multi-select[open]"))
      if (!box.contains(event.target)) box.open = false;
  });
  $("#agent-policy-mode").addEventListener("change", () => {
    const select = $("#agent-policy-grant");
    if ($("#agent-policy-mode").value === "PREAUTHORIZED" && !select.value) {
      const firstActive = [...select.options].find((option) => option.value);
      if (firstActive) select.value = firstActive.value;
    }
    updatePolicyStatusText();
    updatePolicySummary();
    updateBankButtons();
    applyConversationPolicy();
  });
  $("#agent-policy-grant").addEventListener("change", () => {
    updatePolicyStatusText();
    updatePolicySummary();
    updateBankButtons();
    applyConversationPolicy();
  });
  $("#agent-policy-create-grant")?.addEventListener("click", () => {
    setPage("banking");
    const settings = $("#grant-settings");
    if (settings) settings.open = true;
    $("#grant-form")?.scrollIntoView({ block: "start", behavior: "smooth" });
  });
  $("#agent-policy-view")?.addEventListener("click", () => {
    const grantId = $("#agent-policy-grant").value;
    const grant = state.grants.find((item) => item.id === grantId);
    if (!grant) return;
    setPage("banking");
    const settings = $("#grant-settings");
    if (settings) settings.open = true;
    fillGrantFormFromGrant(grant);
    $("#grant-form")?.scrollIntoView({ block: "center", behavior: "smooth" });
    const card = document.querySelector(
      `.grant-card[data-grant-id="${grantId}"]`,
    );
    if (card) {
      card.classList.add("grant-highlight");
      setTimeout(() => card.classList.remove("grant-highlight"), 1600);
    }
  });
  $("#agent-policy-form").addEventListener("submit", (event) => {
    event.preventDefault();
    applyConversationPolicy();
  });
  $("#operation-acknowledged").addEventListener("change", updateBankButtons);
  $("#operation-dialog-close").addEventListener("click", () => {
    if (!state.bankBusy) {
      state.confirmation = null;
      $("#operation-dialog").close();
    }
  });
  $("#operation-dialog").addEventListener("cancel", (event) => {
    if (state.bankBusy) event.preventDefault();
    else state.confirmation = null;
  });
  $("#operation-approve").addEventListener("click", () =>
    runBank(() => decideOperation("approve")),
  );
  $("#operation-reject").addEventListener("click", () =>
    runBank(() => decideOperation("reject")),
  );
}

initializeBanking();
document.addEventListener("DOMContentLoaded", boot, { once: true });
