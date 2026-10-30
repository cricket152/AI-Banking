/** 模拟卡片管理：调额、冻结、挂失均需重新验证登录密码。 */

const CARD_STATUS_LABELS = { active: "正常", frozen: "已冻结", lost: "已挂失" };

function renderCardOptions() {
  const select = $("#card-apply-source");
  if (!select) return;
  const selected = select.value;
  select.replaceChildren(new Option("请选择账户", ""));
  for (const account of state.accounts)
    select.add(new Option(`${account.name} · 尾号 ${account.suffix}`, account.id));
  select.value = selected;
}

function cardButton(label, handler, kind = "secondary") {
  const button = element("button", `button ${kind} bank-action`, label);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

function focusCardField(node, message) {
  bankMessage(message, true);
  node.focus();
  node.scrollIntoView({ block: "center", behavior: "smooth" });
}

function renderCards() {
  const list = $("#cards-list");
  if (!list) return;
  list.replaceChildren();
  const cards = state.cards || [];
  if (!cards.length) {
    list.append(
      element("p", "muted", "暂无模拟卡；可在下方申请一张。"),
    );
    return;
  }
  for (const card of cards) {
    const row = element("article", "operation-card");
    row.append(
      element(
        "strong",
        "",
        `${card.account_name} · ${card.masked_number}`,
      ),
      element(
        "p",
        "",
        `${card.kind} · ${CARD_STATUS_LABELS[card.status] || card.status} · 尾号 ${card.suffix}`,
      ),
      element(
        "p",
        "field-help",
        `日限额 ${currency(card.daily_limit_minor)} · ${card.note}`,
      ),
    );
    if (card.status !== "lost") {
      const actions = element("div", "card-actions");
      const limit = element("input");
      limit.type = "text";
      limit.inputMode = "decimal";
      limit.className = "card-limit";
      limit.value = (card.daily_limit_minor / 100).toFixed(2);
      limit.setAttribute("aria-label", "新的日限额");
      const password = element("input");
      password.type = "password";
      password.className = "card-password";
      password.autocomplete = "current-password";
      password.placeholder = "登录密码";
      password.setAttribute("aria-label", "验证登录密码");
      actions.append(limit, password);
      actions.append(
        cardButton(
          "保存额度",
          () => changeCardLimit(card, limit, password),
          "secondary",
        ),
      );
      actions.append(
        cardButton(
          card.status === "frozen" ? "解冻" : "冻结",
          () =>
            changeCardStatus(
              card,
              card.status === "frozen" ? "active" : "frozen",
              password,
            ),
          "secondary",
        ),
      );
      actions.append(
        cardButton("挂失", () => changeCardStatus(card, "lost", password), "secondary"),
      );
      row.append(actions);
    }
    list.append(row);
  }
}

async function changeCardLimit(card, limitInput, passwordInput) {
  const amount = Math.round(Number(limitInput.value.trim()) * 100);
  if (!limitInput.value.trim() || !Number.isFinite(amount) || amount < 0)
    return focusCardField(limitInput, "请填写正确的日限额。");
  if (!passwordInput.value)
    return focusCardField(passwordInput, "请先输入登录密码再调整额度。");
  try {
    await api(`/api/bank/cards/${card.id}/limit`, {
      method: "POST",
      body: JSON.stringify({
        daily_limit_minor: amount,
        password: passwordInput.value,
      }),
    });
    await loadBankData();
    bankMessage("卡片日限额已更新。");
  } catch (error) {
    bankMessage(error.message, true);
  }
}

async function changeCardStatus(card, status, passwordInput) {
  if (!passwordInput.value)
    return focusCardField(passwordInput, "请先输入登录密码再办理卡片操作。");
  try {
    await api(`/api/bank/cards/${card.id}/status`, {
      method: "POST",
      body: JSON.stringify({ status, password: passwordInput.value }),
    });
    await loadBankData();
    bankMessage(
      status === "lost"
        ? "卡片已挂失；该模拟卡不能继续使用。"
        : status === "frozen"
          ? "卡片已冻结。"
          : "卡片已解冻。",
    );
  } catch (error) {
    bankMessage(error.message, true);
  }
}

function bindCardForm() {
  $("#card-apply-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!$("#card-apply-source").value)
      return focusCardField($("#card-apply-source"), "请选择要绑定的账户。");
    if (!$("#card-apply-password").value)
      return focusCardField($("#card-apply-password"), "请先输入登录密码再申请卡片。");
    const limitText = $("#card-apply-limit").value.trim();
    const limit = limitText ? Math.round(Number(limitText) * 100) : 500000;
    if (!Number.isFinite(limit) || limit < 0)
      return focusCardField($("#card-apply-limit"), "请填写正确的日限额。");
    try {
      await api("/api/bank/cards/apply", {
        method: "POST",
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          account_id: $("#card-apply-source").value,
          kind: $("#card-apply-kind").value,
          daily_limit_minor: limit,
          password: $("#card-apply-password").value,
        }),
      });
      event.target.reset();
      await loadBankData();
      bankMessage("模拟卡已申请；资料仅保存在本地虚构数据中。");
    } catch (error) {
      bankMessage(error.message, true);
    }
  });
}

bindCardForm();
