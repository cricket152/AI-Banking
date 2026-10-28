"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  csrf: "",
  user: null,
  health: null,
  accounts: [],
  transactions: [],
  snapshot: null,
  conversation: null,
  hidden: false,
  sending: false,
  page: "overview",
};
const errors = {
  CREDENTIALS_INVALID: "用户名或密码不正确，或该用户已被停用。",
  AUTH_REQUIRED: "登录已失效，请重新登录。",
  AUTH_UNAVAILABLE: "认证服务暂时不可用，请检查本地服务状态。",
  AUTH_RATE_LIMITED: "尝试过于频繁，请稍后再试。",
  CSRF_REJECTED: "安全凭据已失效，请刷新页面后重试。",
  MODEL_UNAVAILABLE: "模型暂时不可用，请检查服务端配置或网络；本次未获得回答。",
  MODEL_TIMEOUT: "模型处理超过 90 秒，已停止本轮请求。不会自动重试。",
  MODEL_RESPONSE_INVALID: "模型返回格式异常，本次回答未保存。",
  MODEL_RESPONSE_INCOMPLETE:
    "模型回复未完成，已停止本轮。请先核对原操作状态，不要重新发起付款。",
  TOOL_LIMIT:
    "已达到本轮工具调用上限，请先核对原操作，再在原对话继续，不要重新发起付款。",
  CONTEXT_LIMIT:
    "本轮上下文超过安全预算，请先核对原任务状态；暂不继续新增操作。",
  CONVERSATION_BUSY: "当前对话正在处理其他请求，请等待完成。",
  REQUEST_ALREADY_HANDLED: "此请求已处理或正在处理，请刷新查看记录。",
  STORAGE_UNAVAILABLE: "本地数据库暂时不可用，请检查服务端日志和文件权限。",
  INVALID_REQUEST: "输入格式不符合要求，请检查后重试。",
};

async function api(path, options = {}) {
  const requestUser = state.user;
  const headers = { "X-Requested-With": "AI-Banking", ...options.headers };
  if (options.method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRF-Token"] = state.csrf;
  }
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new Error("无法连接本地服务，请确认后端正在运行。请求不会自动重试。");
  }
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) {
    if (
      response.status === 401 &&
      data.code === "AUTH_REQUIRED" &&
      requestUser &&
      state.user === requestUser
    )
      showLogin("登录已失效，请重新登录。");
    const retry = response.headers.get("Retry-After");
    throw new Error(
      (errors[data.code] || `请求失败（${response.status}），请稍后重试。`) +
        (retry ? ` 约 ${retry} 秒后可重试。` : ""),
    );
  }
  return data;
}

function currency(minor) {
  if (state.hidden) return "••••••";
  const sign = minor < 0 ? "−" : "";
  const amount = Math.abs(minor);
  return `${sign}¥${Math.floor(amount / 100).toLocaleString("zh-CN")}.${String(amount % 100).padStart(2, "0")}`;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const ICON_PATHS = {
  card: '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3 10h18M6.5 14.5h4"/>',
  wallet:
    '<path d="M4 8.5A2.5 2.5 0 0 1 6.5 6H17a2 2 0 0 1 2 2v1"/><rect x="3" y="8.5" width="18" height="11" rx="2.5"/><path d="M16 14h1.5"/>',
  dining:
    '<path d="M7 3v8M4.5 3v3.5a2.5 2.5 0 0 0 5 0V3M7 11v10"/><path d="M16 3c-1.4 1.6-2 3.6-2 6 0 1.9 1 2.9 2 2.9V21"/>',
  shopping:
    '<path d="M5.5 8h13l-1 12h-11z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
  transport:
    '<path d="M4 16.5h16M6 16.5l1.4-6.5h9.2l1.4 6.5"/><path d="M8 16.5v2M16 16.5v2"/><circle cx="8.5" cy="13.5" r=".9"/><circle cx="15.5" cy="13.5" r=".9"/>',
  subscription: '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v5h-5"/>',
  income: '<path d="M12 4v13M7 12l5 5 5-5M4 21h16"/>',
  chat: '<path d="M20 11.5a7 7 0 0 1-7 7H9.5L5 21v-3.6a7 7 0 0 1-2-12.3 7 7 0 0 1 13 6.4z"/><path d="M9 10.5h6M9 14h3.5"/>',
};

function icon(name) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.setAttribute("viewBox", "0 0 24 24");
  node.setAttribute("class", "icon");
  node.setAttribute("aria-hidden", "true");
  node.innerHTML = ICON_PATHS[name] || "";
  return node;
}

function showLogin(message = "") {
  resetBanking();
  state.user = null;
  state.csrf = "";
  state.conversation = null;
  state.accounts = [];
  state.transactions = [];
  state.snapshot = null;
  $("#chat-log").replaceChildren();
  $("#accounts-list").replaceChildren();
  $("#transactions-list").replaceChildren();
  for (const selector of [
    "#total-balance",
    "#income",
    "#expense",
    "#profile-name",
  ])
    $(selector).textContent = "—";
  $("#workspace").hidden = true;
  $("#login-view").hidden = false;
  $("#login-error").textContent = message;
  $("#password").value = "";
  $("#settings-dialog").close();
}

async function freshCsrf() {
  state.csrf = (await api("/api/auth/csrf")).csrf_token;
}

function renderAccounts() {
  const container = $("#accounts-list");
  container.replaceChildren();
  for (const account of state.accounts) {
    const card = element("button", "account-card");
    card.type = "button";
    card.setAttribute("aria-label", `查看${account.name}流水`);
    const top = element("div", "account-top");
    const iconNode = element("span", "account-icon");
    iconNode.append(icon(account.kind === "savings" ? "wallet" : "card"));
    top.append(iconNode);
    const name = element("div");
    name.append(
      element("span", "account-name", account.name),
      element("span", "account-suffix", `•••• ${account.suffix}`),
    );
    top.append(name);
    const bottom = element("div", "account-bottom");
    bottom.append(
      element("strong", "account-amount", currency(account.balance_minor)),
      element("span", "", "CNY"),
    );
    card.append(top, bottom);
    card.addEventListener("click", () => {
      setPage("activity");
      $("#account-filter").value = account.id;
      renderTransactions();
      $("#account-filter").focus();
    });
    container.append(card);
  }
}

function renderTransactions() {
  const filter = $("#account-filter").value;
  const transactions = state.transactions.filter(
    (row) => !filter || row.account_id === filter,
  );
  const list = $("#transactions-list");
  list.replaceChildren();
  const icons = {
    餐饮: "dining",
    购物: "shopping",
    交通: "transport",
    订阅: "subscription",
    收入: "income",
  };
  for (const entry of transactions) {
    const row = element("tr");
    const merchant = element("div", "merchant");
    const merchantIcon = element("span", "merchant-icon");
    merchantIcon.append(icon(icons[entry.category] || "card"));
    merchant.append(merchantIcon);
    const label = element("div");
    label.append(
      element("span", "merchant-name", entry.merchant),
      element(
        "span",
        "merchant-category",
        `${entry.category} · ${entry.account_name}`,
      ),
    );
    merchant.append(label);
    const merchantCell = element("td");
    merchantCell.append(merchant);
    const date = new Date(entry.happened_at).toLocaleDateString("zh-CN", {
      timeZone: "Asia/Shanghai",
      month: "2-digit",
      day: "2-digit",
    });
    const amountCell = element("td");
    amountCell.append(
      element(
        "span",
        `transaction-amount${entry.amount_minor > 0 ? " incoming" : ""}`,
        `${entry.amount_minor > 0 && !state.hidden ? "+" : ""}${currency(entry.amount_minor)}`,
      ),
    );
    row.append(merchantCell, element("td", "", date), amountCell);
    list.append(row);
  }
  $("#transactions-empty").hidden = transactions.length !== 0;
}

function renderMoney() {
  if (!state.snapshot) return;
  $("#total-balance").textContent = currency(state.snapshot.total_minor);
  const income = state.transactions.reduce(
    (sum, row) => sum + Math.max(0, row.amount_minor),
    0,
  );
  const expense = state.transactions.reduce(
    (sum, row) => sum - Math.min(0, row.amount_minor),
    0,
  );
  $("#income").textContent = currency(income);
  $("#expense").textContent = currency(expense);
  $("#metric-accounts").textContent = String(state.accounts.length).padStart(
    2,
    "0",
  );
  $("#account-count").textContent = `${state.accounts.length} 个账户`;
  $("#accounts-badge").textContent = state.accounts.length;
  $("#snapshot-time").textContent =
    `更新于 ${new Date(state.snapshot.as_of).toLocaleTimeString("zh-CN")}`;
  renderAccounts();
  renderTransactions();
  renderBanking();
}

async function loadData() {
  const user = state.user;
  const [accounts, entries] = await Promise.all([
    api("/api/accounts"),
    api("/api/transactions"),
  ]);
  if (!user || state.user !== user) return;
  state.accounts = accounts.accounts;
  state.snapshot = accounts.snapshot;
  state.transactions = entries.transactions;
  const selected = $("#account-filter").value;
  $("#account-filter").replaceChildren(new Option("全部账户", ""));
  for (const account of state.accounts)
    $("#account-filter").add(new Option(account.name, account.id));
  $("#account-filter").value = selected;
  renderMoney();
}

const pageTitles = {
  overview: [
    "财务概览",
    "你的财务，一目了然",
    "从这里了解你的资产，也可以直接问问 AI 助手。",
  ],
  accounts: [
    "我的账户",
    "每个账户，清晰可见",
    "选择一个账户，查看它的模拟交易记录。",
  ],
  activity: [
    "收支明细",
    "每一笔，都有迹可循",
    "按账户查看最近流水；这里展示的是虚构的样本数据。",
  ],
  assistant: [
    "AI 助手",
    "理清财务，从聊一聊开始",
    "账户与收支问题，交给你的 Banking 助手。",
  ],
  banking: [
    "业务办理",
    "每次执行，都清楚确认",
    "转账、订阅与预授权，在这里核对和管理。",
  ],
};

function setPage(page) {
  state.page = page;
  const [label, title, description] = pageTitles[page];
  $("#breadcrumb").textContent = label;
  $("#page-title").replaceChildren(
    document.createTextNode(title),
    element("span", "title-dot", "."),
  );
  $("#page-description").textContent = description;
  document.querySelectorAll("nav [data-page]").forEach((button) => {
    const active = button.dataset.page === page;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#finance-pane").hidden = page === "assistant" || page === "banking";
  $("#bank-pane").hidden = page !== "banking";
  $("#overview-section").hidden = page !== "overview";
  $("#accounts-section").hidden = page === "activity";
  $("#activity-section").hidden = page === "accounts";
  $(".content").classList.toggle("assistant-only", page === "assistant");
  if (page === "assistant") $("#chat-input").focus();
}

function welcome() {
  const node = element("div", "chat-welcome");
  const welcomeIcon = element("div", "chat-welcome-icon");
  welcomeIcon.append(icon("chat"));
  node.append(
    welcomeIcon,
    element("h3", "", "你好，有什么想了解的？"),
    element("p", "", "我可以帮你查看账户和最近收支，让财务信息更容易理解。"),
    element(
      "small",
      "",
      state.health.agent_mode === "offline"
        ? "目前是离线演示：使用本地规则查询，不调用大模型。"
        : "默认每笔在确认卡片批准；选择预授权后可在范围内执行。对话与模拟数据会发送给配置的供应商。",
    ),
  );
  $("#chat-log").replaceChildren(node);
  $("#suggestions").hidden = false;
}

function addMessage(role, text, traces = []) {
  $(".chat-welcome")?.remove();
  const message = element("div", `message ${role}`, text);
  if (traces.length)
    message.append(
      element("span", "tool-trace", `工具轨迹 · ${traces.join(" → ")}`),
    );
  $("#chat-log").append(message);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  return message;
}

async function loadConversation() {
  const user = state.user;
  const list = await api("/api/conversations");
  if (!user || state.user !== user) return;
  if (list.conversations.length) {
    state.conversation = list.conversations[0].id;
    const { turns, operation_task, execution_policy } = await api(
      `/api/conversations/${state.conversation}`,
    );
    if (state.user !== user) return;
    welcome();
    state.operationTask = operation_task;
    state.executionPolicy = execution_policy;
    for (const turn of turns) {
      addMessage("user", turn.question);
      addMessage(
        turn.status === "succeeded" ? "assistant" : "error",
        turn.answer ||
          "这条请求未完成，未获得回答。可以新发一条消息；系统不会自动重试。",
        turn.traces ? JSON.parse(turn.traces) : [],
      );
    }
    $("#suggestions").hidden = turns.length > 0;
  } else {
    state.conversation = (
      await api("/api/conversations", { method: "POST", body: "{}" })
    ).id;
    welcome();
  }
}

async function enterWorkspace() {
  state.user = await api("/api/auth/me");
  state.workflowReady = false;
  updateBankButtons();
  await freshCsrf();
  $("#login-view").hidden = true;
  $("#workspace").hidden = false;
  $("#profile-name").textContent = state.user.username;
  $("#avatar").textContent = state.user.username[0];
  const model = state.health.agent_mode === "model";
  $("#agent-mode").textContent = model
    ? `模型模式 · ${state.health.model}`
    : "离线演示 · 本地规则";
  $("#agent-disclaimer").textContent = model
    ? "模型回答仅供辅助，金额以账户数据为准。"
    : "离线演示由本地规则响应，不代表已连接 LLM。";
  $("#settings-mode").textContent = model
    ? `${state.health.model} · ${state.health.model_api}`
    : "offline · 未连接大模型";
  $("#app-error").hidden = true;
  await Promise.all([loadData(), loadConversation()]);
  await loadBankData();
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-error").textContent = "";
  $("#login-submit").disabled = true;
  try {
    await freshCsrf();
    const password = $("#password").value;
    $("#password").value = "";
    const result = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("#username").value,
        password,
      }),
    });
    state.csrf = result.csrf_token;
    await enterWorkspace();
  } catch (error) {
    $(state.user ? "#app-error" : "#login-error").textContent = error.message;
    if (state.user) $("#app-error").hidden = false;
  } finally {
    $("#password").value = "";
    $("#login-submit").disabled = false;
  }
});

$("#toggle-password").addEventListener("click", () => {
  const visible = $("#password").type === "password";
  $("#password").type = visible ? "text" : "password";
  $("#toggle-password").textContent = visible ? "隐藏" : "显示";
  $("#toggle-password").setAttribute(
    "aria-label",
    visible ? "隐藏密码" : "显示密码",
  );
  $("#toggle-password").setAttribute("aria-pressed", visible);
});

$("#logout").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
    showLogin();
  } catch (error) {
    $("#app-error").textContent = error.message;
    $("#app-error").hidden = false;
  }
});

document
  .querySelectorAll("[data-page]")
  .forEach((button) =>
    button.addEventListener("click", () => setPage(button.dataset.page)),
  );
$("#account-filter").addEventListener("change", renderTransactions);
$("#toggle-balance").addEventListener("click", () => {
  state.hidden = !state.hidden;
  $("#toggle-balance").setAttribute("aria-pressed", state.hidden);
  $("#toggle-balance").setAttribute(
    "aria-label",
    state.hidden ? "显示金额" : "隐藏金额",
  );
  renderMoney();
});
$("#refresh").addEventListener("click", async () => {
  $("#refresh").disabled = true;
  $("#app-error").hidden = true;
  try {
    await Promise.all([loadData(), loadBankData()]);
  } catch (error) {
    $("#app-error").textContent = error.message;
    $("#app-error").hidden = false;
  } finally {
    $("#refresh").disabled = false;
  }
});

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("#chat-input").value.trim();
  if (
    !question ||
    state.sending ||
    state.bankBusy ||
    !state.workflowReady ||
    !state.conversation
  )
    return;
  const user = state.user;
  const conversation = state.conversation;
  state.sending = true;
  updateBankButtons();
  $("#chat-send").disabled = true;
  $("#new-chat").disabled = true;
  $("#suggestions").hidden = true;
  $("#chat-input").value = "";
  addMessage("user", question);
  const pending = addMessage("assistant", "正在处理，请稍候…");
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        conversation_id: state.conversation,
        request_id: crypto.randomUUID(),
        message: question,
      }),
    });
    pending.remove();
    if (state.user === user && state.conversation === conversation)
      addMessage("assistant", result.answer, result.traces);
  } catch (error) {
    pending.remove();
    if (state.user === user && state.conversation === conversation)
      addMessage("error", error.message);
  } finally {
    if (state.user === user && state.conversation === conversation) {
      try {
        await Promise.all([loadData(), loadBankData()]);
      } catch {
        addMessage(
          "error",
          "暂时无法刷新后端操作状态，请点击刷新数据核实原操作，不要重复付款。",
        );
      }
    }
    state.sending = false;
    $("#chat-send").disabled = false;
    $("#new-chat").disabled = false;
    if (state.user) $("#chat-input").focus();
    updateBankButtons();
  }
});
$("#chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("#chat-form").requestSubmit();
  }
});
document.querySelectorAll("[data-prompt]").forEach((button) =>
  button.addEventListener("click", () => {
    $("#chat-input").value = button.dataset.prompt;
    $("#chat-form").requestSubmit();
  }),
);
$("#new-chat").addEventListener("click", async () => {
  if (state.sending || state.bankBusy || !state.workflowReady) return;
  const previousConversation = state.conversation;
  state.workflowReady = false;
  updateBankButtons();
  $("#new-chat").disabled = true;
  try {
    state.conversation = (
      await api("/api/conversations", { method: "POST", body: "{}" })
    ).id;
    state.operationTask = null;
    state.executionPolicy = null;
    welcome();
    await loadBankData();
    $("#chat-input").focus();
  } catch (error) {
    if (state.conversation === previousConversation) state.workflowReady = true;
    if (state.user) addMessage("error", error.message);
  } finally {
    $("#new-chat").disabled = false;
    updateBankButtons();
  }
});
$("#settings-open").addEventListener("click", () =>
  $("#settings-dialog").showModal(),
);
$("#settings-close").addEventListener("click", () =>
  $("#settings-dialog").close(),
);
$("#settings-done").addEventListener("click", () =>
  $("#settings-dialog").close(),
);

async function boot() {
  $("#today").textContent = new Date().toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  try {
    state.health = await api("/api/health");
    $("#setup-note").hidden = !state.health.setup_required;
    const response = await fetch("/api/auth/me", {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (response.ok) await enterWorkspace();
    else if (response.status !== 401)
      throw new Error("无法恢复会话，请检查本地服务。");
  } catch (error) {
    $(state.user ? "#app-error" : "#login-error").textContent = error.message;
    if (state.user) $("#app-error").hidden = false;
  }
}
