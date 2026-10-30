/** 模拟理财申购/赎回：只创建待确认操作，不连接真实产品。 */

function renderWealthOptions() {
  const product = $("#wealth-product");
  if (product) {
    const selected = product.value;
    product.replaceChildren(new Option("请选择产品", ""));
    for (const item of state.wealth?.products || [])
      product.add(new Option(`${item.name} · ${item.risk_level}`, item.id));
    product.value = selected;
  }
  const source = $("#wealth-source");
  if (source) {
    const selected = source.value;
    source.replaceChildren(new Option("请选择账户", ""));
    for (const account of state.accounts)
      source.add(new Option(`${account.name} · 尾号 ${account.suffix} · ${currency(account.balance_minor)}`, account.id));
    source.value = selected;
  }
}

function renderWealth() {
  const products = $("#wealth-products");
  const holdings = $("#wealth-holdings");
  if (!products || !holdings) return;
  products.replaceChildren();
  for (const item of state.wealth?.products || []) {
    const row = element("article", "operation-card");
    row.append(
      element("strong", "", item.name),
      element("p", "", `${item.kind} · ${item.risk_level} · 起投 ${currency(item.min_amount_minor)}`),
      element("p", "field-help", `${item.yield_hint} · 模拟收益，不保证`),
    );
    products.append(row);
  }
  holdings.replaceChildren();
  const items = state.wealth?.holdings || [];
  if (!items.length) {
    holdings.append(element("p", "muted", "暂无模拟持仓。"));
    return;
  }
  for (const holding of items) {
    const row = element("article", "operation-card");
    row.append(
      element("strong", "", `持仓 · ${holding.product.name}`),
      element("p", "", `当前模拟持仓 ${currency(holding.amount_minor)}`),
      element("p", "field-help", `${holding.product.risk_level} · 赎回按当前模拟金额，不保证收益`),
    );
    holdings.append(row);
  }
}

function focusWealthField(node, message) {
  bankMessage(message, true);
  node.focus();
  node.scrollIntoView({ block: "center", behavior: "smooth" });
}

function bindWealthForm() {
  $("#wealth-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!$("#wealth-product").value)
      return focusWealthField($("#wealth-product"), "请选择理财产品。");
    if (!$("#wealth-source").value)
      return focusWealthField($("#wealth-source"), "请选择账户。");
    const amountText = $("#wealth-amount").value.trim();
    const amount = Math.round(Number(amountText) * 100);
    if (!amountText || !Number.isFinite(amount) || amount <= 0)
      return focusWealthField($("#wealth-amount"), "请填写正确的金额。");
    try {
      const result = await api("/api/bank/wealth/orders", {
        method: "POST",
        body: JSON.stringify({
          product_id: $("#wealth-product").value,
          action: $("#wealth-action").value,
          source_id: $("#wealth-source").value,
          amount_minor: amount,
        }),
      });
      await loadBankData();
      bankMessage("已准备理财操作；请核对确认单，批准前不会改变余额或持仓。");
      openOperation(result.operation.id);
    } catch (error) {
      bankMessage(error.message, true);
    }
  });
}

bindWealthForm();
