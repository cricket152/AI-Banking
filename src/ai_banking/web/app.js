const stateUrl = "/api/state";
const moneyFormatter = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
});
const labels = {
  overview: "总览",
  transfer: "转账与收款",
  bills: "账单分析",
  investments: "理财投资",
  cards: "卡片管理",
  subscriptions: "订阅管理",
  birthday: "生日联动",
};
let bankState = null;
let activeView = "overview";
let busy = false;
let messages = [{
  role: "assistant",
  text: "早上好，知夏。今天想先处理哪件事？",
}];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function money(cents) {
  return moneyFormatter.format((Number(cents) || 0) / 100);
}

function shortDate(value) {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function fullDate(value = new Date()) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(value);
}

function notify(message, isError = false) {
  const toast = document.createElement("div");
  toast.className = `toast${isError ? " error" : ""}`;
  toast.textContent = message;
  $("#toast-region").append(toast);
  window.setTimeout(() => toast.remove(), 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.message || "请求未完成，请稍后重试。");
  }
  return data;
}

async function loadState() {
  bankState = await api(stateUrl);
  render();
}

function setView(view) {
  activeView = view in labels ? view : "overview";
  $$(".nav-item").forEach((button) => {
    const selected = button.dataset.view === activeView;
    button.classList.toggle("active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#view-label").textContent = labels[activeView];
  render();
  if (window.matchMedia("(max-width: 760px)").matches) {
    $("#main-content").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function render() {
  if (!bankState) return;
  $("#today-label").textContent = fullDate();
  $("#assistant-context").textContent = `演示账户 · ${bankState.profile.name}`;
  $(".notification-button i").hidden = bankState.reminders.length === 0;
  $("#main-content").innerHTML = renderView();
  renderMessages();
}

function heading(title, subtitle, action = "") {
  return `
    <div class="page-heading">
      <div><div class="eyebrow">澄明银行 · 个人账户</div><h1>${title}</h1><p>${subtitle}</p></div>
      ${action}
    </div>`;
}

function renderView() {
  switch (activeView) {
    case "transfer": return renderTransfer();
    case "bills": return renderBills();
    case "investments": return renderInvestments();
    case "cards": return renderCards();
    case "subscriptions": return renderSubscriptions();
    case "birthday": return renderBirthday();
    default: return renderOverview();
  }
}

function renderOverview() {
  const totalFunds = bankState.funds.reduce((sum, fund) => sum + fund.holding_cents, 0);
  const checking = bankState.accounts.find((account) => account.id === "checking");
  const savings = bankState.accounts.find((account) => account.id === "savings");
  const maxSpend = Math.max(1, ...bankState.monthly_categories.map((item) => item.amount_cents));
  const categories = bankState.monthly_categories.slice(0, 4);
  const recent = bankState.transactions.slice(0, 5);
  return `
    ${heading(
      `早上好，${escapeHtml(bankState.profile.name)}`,
      "你的账户和近期金融活动一览",
      '<button class="primary-button" data-prompt="转 88 元给周明"><span>＋</span>发起转账</button>',
    )}
    <section class="overview-hero" aria-label="资产概况">
      <div class="hero-label">总资产</div>
      <div class="hero-balance">${money(bankState.net_assets_cents)}</div>
      <div class="hero-caption">含活期、储蓄与基金持仓 · 本地演示数据</div>
      <div class="hero-metrics">
        <div class="hero-metric"><span>日常账户可用</span><strong>${money(bankState.checking_available_cents)}</strong></div>
        <div class="hero-metric"><span>安心储蓄</span><strong>${money(savings.balance_cents)}</strong></div>
        <div class="hero-metric"><span>基金持仓</span><strong>${money(totalFunds)}</strong></div>
      </div>
      <div class="hero-actions">
        <button data-view="transfer">转账</button>
        <button data-view="bills">查看账单</button>
      </div>
    </section>
    <section class="quick-section">
      <div class="section-heading"><div><h2>快捷场景</h2><p>常用账户服务</p></div></div>
      <div class="quick-grid">
        <button class="quick-action" data-prompt="转 88 元给周明"><span class="quick-icon">⇄</span><span>智能转账</span></button>
        <button class="quick-action" data-prompt="分析本月账单并检查异常交易"><span class="quick-icon">▤</span><span>账单分析</span></button>
        <button class="quick-action" data-prompt="比较适合稳健型的理财产品"><span class="quick-icon">↗</span><span>理财对比</span></button>
        <button class="quick-action" data-prompt="锁定澄明白金卡"><span class="quick-icon">▣</span><span>卡片管理</span></button>
        <button class="quick-action" data-prompt="分析我的订阅扣费"><span class="quick-icon">↻</span><span>订阅管理</span></button>
        <button class="quick-action" data-prompt="安排爱人生日：11月5日锁定1000元，提前订鲜花和蛋糕"><span class="quick-icon">✳</span><span>生日联动</span></button>
      </div>
    </section>
    <div class="dashboard-columns">
      <section class="section-block">
        <div class="section-heading">
          <div><h2>本月支出</h2><p>按演示交易记录归类</p></div>
          <span class="period-label">${new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long" }).format(new Date())}</span>
        </div>
        <div class="spending-total">${money(bankState.monthly_spending_cents)}<small>较上月 —</small></div>
        <div class="spending-chart">
          ${categories.map((item) => `
            <div class="spending-row">
              <span>${escapeHtml(item.name)}</span>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, item.amount_cents / maxSpend * 100)}%"></div></div>
              <strong>${money(item.amount_cents)}</strong>
            </div>`).join("")}
        </div>
        <hr class="panel-divider">
        ${bankState.anomalies.length ? `
          <div class="insight-row"><span class="insight-icon">!</span><span>有 ${bankState.anomalies.length} 笔交易需要你核对：${escapeHtml(bankState.anomalies[0].merchant)} ${money(bankState.anomalies[0].amount_cents)}。标记仅供演示参考。</span></div>
        ` : '<div class="insight-row"><span class="insight-icon">✓</span><span>目前没有需要核对的演示交易。</span></div>'}
      </section>
      <section class="section-block">
        <div class="section-heading">
          <div><h2>近期交易</h2><p>最新账户活动</p></div>
          <button class="text-button" data-view="bills">全部记录 →</button>
        </div>
        <div class="transaction-list">${recent.map(renderTransaction).join("")}</div>
      </section>
    </div>
    <section class="section-block">
      <div class="section-heading"><div><h2>我的账户</h2><p>关联账户余额</p></div></div>
      <div class="account-grid">${bankState.accounts.map((account) => `
        <div class="account-tile">
          <div class="account-tile-top"><span>${escapeHtml(account.name)} · ${escapeHtml(account.kind)}</span><span class="account-dot ${account.color === "blue" ? "blue" : ""}"></span></div>
          <strong>${money(account.balance_cents)}</strong>
          <small>${escapeHtml(account.number)}${account.held_cents ? ` · 已预留 ${money(account.held_cents)}` : ""}</small>
        </div>`).join("")}</div>
    </section>`;
}

function renderTransaction(transaction) {
  const isIncome = transaction.direction === "in";
  const symbol = transaction.category === "订阅" ? "↻" : transaction.category === "理财" ? "↗" : transaction.category === "转账" ? "⇄" : isIncome ? "↓" : "•";
  return `
    <div class="transaction-row">
      <span class="transaction-symbol ${isIncome ? "income" : ""}">${symbol}</span>
      <span class="transaction-name"><strong>${escapeHtml(transaction.merchant)}</strong><small>${shortDate(transaction.date)} · ${escapeHtml(transaction.category)}</small></span>
      <span class="transaction-amount ${isIncome ? "income" : ""}">${isIncome ? "+" : "−"}${money(transaction.amount_cents)}</span>
    </div>`;
}

function renderTransfer() {
  const contacts = bankState.contacts;
  const scheduled = bankState.scheduled_transfers;
  const requests = bankState.collection_requests;
  return `
    ${heading("转账与收款", "向联系人转账、预约付款或创建 AA 收款单")}
    <div class="metric-grid">
      <div class="metric-tile"><span>日常账户可用</span><strong>${money(bankState.checking_available_cents)}</strong></div>
      <div class="metric-tile"><span>常用联系人</span><strong>${contacts.length} 位</strong></div>
      <div class="metric-tile"><span>待执行预约</span><strong>${scheduled.length} 笔</strong></div>
    </div>
    <section class="section-block">
      <div class="section-heading"><div><h2>常用联系人</h2><p>转账前会再次显示姓名与金额供确认</p></div></div>
      <div class="contact-list">${contacts.map((contact) => `
        <div class="contact-row">
          <div class="contact-main"><span class="contact-avatar">${escapeHtml(contact.name.slice(0, 1))}</span><span class="contact-copy"><strong>${escapeHtml(contact.name)}</strong><small>${escapeHtml(contact.phone)}</small></span></div>
          <button class="secondary-button" data-prompt="转 88 元给${escapeHtml(contact.name)}">转账</button>
        </div>`).join("")}</div>
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>常用操作</h2></div></div>
      <div class="view-toolbar">
        <button class="secondary-button" data-prompt="预约明天转 88 元给周明">预约转账</button>
        <button class="secondary-button" data-prompt="把 306 元拆成 3 人 AA，邀请周明和妈妈">创建 AA 收款</button>
      </div>
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>预约转账</h2><p>预约操作仅保存在本地模拟状态</p></div></div>
      ${scheduled.length ? `<table class="data-table"><thead><tr><th>收款人</th><th>执行日期</th><th>状态</th><th>金额</th></tr></thead><tbody>${scheduled.map((item) => `<tr><td>${escapeHtml(item.recipient)}</td><td>${escapeHtml(item.date)}</td><td><span class="flag ${item.status === "completed" ? "ok" : ""}">${item.status === "completed" ? "已执行" : item.status === "failed" ? "执行失败" : "待执行"}</span></td><td>${money(item.amount_cents)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty-state">暂无预约转账</div>'}
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>AA 收款单</h2><p>创建后不会自动向联系人催款</p></div></div>
      ${requests.length ? requests.map((item) => `<div class="product-row"><div class="product-main"><span class="product-icon">⇄</span><span class="product-copy"><strong>${escapeHtml(item.title)}</strong><small>${item.people} 人（含你） · 你的份额 ${money(item.payer_share_cents)} · ${item.participants.map((person) => `${escapeHtml(person.name)} ${money(person.amount_cents)}`).join("、")}</small></span></div><strong>${money(item.total_cents)}</strong></div>`).join("") : '<div class="empty-state">暂无 AA 收款单</div>'}
    </section>`;
}

function renderBills() {
  const categories = bankState.monthly_categories;
  const maxSpend = Math.max(1, ...categories.map((item) => item.amount_cents));
  return `
    ${heading("账单分析", "消费分类、周期汇总与异常交易提示")}
    <div class="metric-grid">
      <div class="metric-tile"><span>本月非转账支出</span><strong>${money(bankState.monthly_spending_cents)}</strong></div>
      <div class="metric-tile"><span>消费类别</span><strong>${categories.length} 类</strong></div>
      <div class="metric-tile"><span>待核对提示</span><strong>${bankState.anomalies.length} 笔</strong></div>
    </div>
    <section class="section-block">
      <div class="section-heading"><div><h2>消费分类</h2><p>依据当前演示交易记录计算</p></div><button class="secondary-button" data-prompt="分析本月账单并检查异常交易">生成月报</button></div>
      ${categories.length ? `<div class="spending-chart">${categories.map((item) => `<div class="spending-row"><span>${escapeHtml(item.name)}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, item.amount_cents / maxSpend * 100)}%"></div></div><strong>${money(item.amount_cents)}</strong></div>`).join("")}</div>` : '<div class="empty-state">暂无本月支出</div>'}
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>异常交易识别</h2><p>规则标记仅作为人工核对线索，不代表欺诈结论</p></div></div>
      ${bankState.anomalies.length ? `<table class="data-table"><thead><tr><th>商户</th><th>日期</th><th>说明</th><th>金额</th></tr></thead><tbody>${bankState.anomalies.map((item) => `<tr><td>${escapeHtml(item.merchant)}</td><td>${shortDate(item.date)}</td><td><span class="flag">待人工核对</span></td><td>${money(item.amount_cents)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty-state">暂无待核对交易</div>'}
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>交易明细</h2><p>本地演示账户记录</p></div><button class="secondary-button" data-prompt="生成本月账单月报">查看月报摘要</button></div>
      <div class="transaction-list">${bankState.transactions.map(renderTransaction).join("")}</div>
    </section>`;
}

function renderInvestments() {
  return `
    ${heading("理财投资", "查看风险指标与持仓；申购和赎回均需确认")}
    <div class="subtle-callout"><span>i</span><span><strong>风险提示</strong>演示收益率与波动率为静态样例，不代表未来表现或真实产品信息。请结合自身风险承受能力判断。</span></div>
    <section class="section-block">
      <div class="section-heading"><div><h2>持仓概览</h2><p>共 ${bankState.funds.length} 项演示产品</p></div><button class="secondary-button" data-prompt="比较适合稳健型的理财产品">AI 风险对比</button></div>
      <div class="metric-grid">
        <div class="metric-tile"><span>基金持仓</span><strong>${money(bankState.funds.reduce((sum, fund) => sum + fund.holding_cents, 0))}</strong></div>
        <div class="metric-tile"><span>风险偏好</span><strong>${escapeHtml(bankState.profile.risk_profile)}</strong></div>
        <div class="metric-tile"><span>当前产品</span><strong>${bankState.funds.length} 项</strong></div>
      </div>
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>产品对比</h2><p>风险等级 1–5，数值越高波动通常越大</p></div></div>
      <div class="product-list">${bankState.funds.map((fund) => `
        <div class="product-row">
          <div class="product-main"><span class="product-icon">↗</span><span class="product-copy"><strong>${escapeHtml(fund.name)}</strong><small>${escapeHtml(fund.category)} · ${escapeHtml(fund.description)}</small></span></div>
          <div class="product-stats">
            <span>演示年化<strong>${(fund.annual_return * 100).toFixed(1)}%</strong></span>
            <span>风险等级<strong>${fund.risk} / 5</strong></span>
            <span>持仓<strong>${money(fund.holding_cents)}</strong></span>
          </div>
          <div class="product-actions"><button class="secondary-button" data-prompt="申购${escapeHtml(fund.name)} 500 元">申购</button><button class="text-button" data-prompt="赎回${escapeHtml(fund.name)} 500 元">赎回</button></div>
        </div>`).join("")}</div>
    </section>`;
}

function renderCards() {
  return `
    ${heading("卡片管理", "查看卡片状态、调整额度或保护遗失卡片")}
    <div class="metric-grid">
      <div class="metric-tile"><span>卡片数量</span><strong>${bankState.cards.length} 张</strong></div>
      <div class="metric-tile"><span>正常卡片</span><strong>${bankState.cards.filter((card) => card.status === "active").length} 张</strong></div>
      <div class="metric-tile"><span>受理中申请</span><strong>0 项</strong></div>
    </div>
    <div class="card-grid">${bankState.cards.map((card) => `
      <section>
        <div class="bank-card ${card.color === "mint" ? "mint" : ""} ${card.status === "locked" ? "locked" : ""}">
          <div class="bank-card-top"><strong>${escapeHtml(card.name)}</strong><span>${escapeHtml(card.kind)}</span></div>
          <div class="card-chip" aria-hidden="true"></div>
          <div class="bank-card-bottom"><strong>${escapeHtml(card.number)}</strong><span>${card.status === "active" ? "ACTIVE" : "LOCKED"}</span></div>
        </div>
        <div class="card-detail"><span>可用额度</span><strong>${money(card.limit_cents - card.used_cents)} / ${money(card.limit_cents)}</strong></div>
        <div class="card-detail"><span>单日交易限额</span><strong>${money(card.daily_limit_cents)}</strong></div>
        <div class="card-controls">
          ${card.status === "active"
            ? `<button class="secondary-button" data-prompt="锁定${escapeHtml(card.name)}">锁定卡片</button>`
            : `<button class="primary-button" data-prompt="解锁${escapeHtml(card.name)}">解锁卡片</button>`}
          <button class="text-button" data-prompt="${escapeHtml(card.name)}额度调到 60000 元">调整额度</button>
          <button class="text-button" data-prompt="${escapeHtml(card.name)}单日交易限额调到 3000 元">调整日限额</button>
        </div>
      </section>`).join("")}</div>
    <section class="section-block">
      <div class="section-heading"><div><h2>安全设置</h2><p>任何状态或额度变更都会先显示确认内容</p></div></div>
      <button class="secondary-button" data-prompt="申请一张新卡">申请演示数字卡</button>
    </section>`;
}

function renderSubscriptions() {
  const active = bankState.subscriptions.filter((item) => item.status === "active");
  const cancelled = bankState.subscriptions.filter((item) => item.status !== "active");
  return `
    ${heading("订阅管理", "识别周期扣费、查看续费时间并管理提醒")}
    <div class="metric-grid">
      <div class="metric-tile"><span>活跃订阅</span><strong>${active.length} 项</strong></div>
      <div class="metric-tile"><span>月度费用</span><strong>${money(bankState.active_subscription_total_cents)}</strong></div>
      <div class="metric-tile"><span>已取消</span><strong>${cancelled.length} 项</strong></div>
    </div>
    <section class="section-block">
      <div class="section-heading"><div><h2>周期扣费</h2><p>费用从演示交易与订阅清单中识别</p></div><button class="secondary-button" data-prompt="分析我的订阅扣费">AI 汇总</button></div>
      <div class="subscription-list">${bankState.subscriptions.map((item) => `
        <div class="subscription-row ${item.status === "active" ? "" : "is-cancelled"}">
          <div class="subscription-main"><span class="subscription-icon">↻</span><span class="subscription-copy"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.category)} · ${escapeHtml(item.period)}扣费 · ${item.status === "active" ? "续费中" : "已取消"}</small></span></div>
          <div class="subscription-info"><strong>${money(item.amount_cents)}</strong><small>${item.status === "active" ? `下次扣费 ${shortDate(item.next_charge)}` : "不会再次续费"}</small></div>
          ${item.status === "active" ? `<div class="subscription-actions"><button class="text-button" data-prompt="提醒我${escapeHtml(item.name)}续费">设提醒</button><button class="secondary-button" data-prompt="取消${escapeHtml(item.name)}订阅">取消订阅</button></div>` : ""}
          ${item.reminder ? '<span class="flag ok">提醒已设</span>' : ""}
        </div>`).join("")}</div>
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>续费日历</h2><p>未来 30 天的已知周期扣费</p></div></div>
      ${active.length ? `<div class="timeline">${active.slice().sort((a, b) => a.next_charge.localeCompare(b.next_charge)).map((item) => `<div class="timeline-row"><span class="timeline-date">${shortDate(item.next_charge)}</span><span class="timeline-marker"><i></i></span><span class="timeline-copy"><strong>${escapeHtml(item.name)} · ${money(item.amount_cents)}</strong><small>${item.reminder ? "已设置续费提醒" : "可设置续费提醒"}</small></span></div>`).join("")}</div>` : '<div class="empty-state">暂无续费安排</div>'}
    </section>`;
}

function renderBirthday() {
  const birthday = bankState.profile.partner_birthday;
  const plans = bankState.birthday_plans;
  return `
    ${heading("生日联动", "资金预留与礼物提醒协同安排")}
    <div class="birthday-banner">
      <div><div class="eyebrow">已保存的家庭日期</div><h2>林小满 · ${shortDate(birthday)}</h2><p>提交前可在对话中指定其他日期、预留金额或联系人。</p></div>
      <div class="birthday-mark" aria-hidden="true">✿</div>
    </div>
    <section class="section-block">
      <div class="section-heading"><div><h2>创建联动安排</h2><p>先预览资金影响，确认后再写入模拟账户</p></div></div>
      <div class="subtle-callout"><span>i</span><span>确认后会将资金标记为已预留，并创建提前两天的礼物提醒。礼物不会自动下单，预留金额仍计入总余额。</span></div>
      <div class="view-toolbar" style="margin-top:14px">
        <button class="primary-button" data-prompt="安排爱人生日：11月5日锁定1000元，提前订鲜花和蛋糕">安排生日联动</button>
        <button class="secondary-button" data-prompt="安排爱人生日：11月5日锁定1000元，提前订鲜花和蛋糕">预览默认安排</button>
      </div>
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>安排记录</h2><p>预留资金与礼物提醒</p></div></div>
      ${plans.length ? `<div class="timeline">${plans.map((plan) => `
        <div class="timeline-row"><span class="timeline-date">${shortDate(plan.gift_order_date)}</span><span class="timeline-marker"><i></i></span><span class="timeline-copy"><strong>预订${plan.gifts.map(escapeHtml).join("和")} · ${escapeHtml(plan.recipient)}</strong><small>预留 ${money(plan.reserve_cents)} · 生日 ${shortDate(plan.date)}</small></span></div>
        <div class="timeline-row"><span class="timeline-date">${shortDate(plan.date)}</span><span class="timeline-marker"><i></i></span><span class="timeline-copy"><strong>${escapeHtml(plan.recipient)}生日</strong><small>预留资金 ${money(plan.reserve_cents)} · ${plan.status === "scheduled" ? "待执行" : "已完成"}</small></span></div>`).join("")}</div>` : '<div class="empty-state">还没有生日联动安排</div>'}
    </section>
    <section class="section-block">
      <div class="section-heading"><div><h2>资金预留</h2></div></div>
      <div class="account-grid">${bankState.accounts.map((account) => `<div class="account-tile"><div class="account-tile-top"><span>${escapeHtml(account.name)}</span><span>${account.held_cents ? "已预留" : "可用"}</span></div><strong>${money(account.held_cents || account.balance_cents)}</strong><small>${account.held_cents ? `可用余额 ${money(account.balance_cents - account.held_cents)}` : "当前没有预留资金"}</small></div>`).join("")}</div>
    </section>`;
}

function renderMessages() {
  const container = $("#chat-messages");
  container.innerHTML = messages.map((message) => {
    const plan = message.plan?.length
      ? `<ol class="message-plan">${message.plan.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>`
      : "";
    const tools = message.tools?.length
      ? `<div class="tool-trace">${message.tools.map((tool) => `<span><i></i>${escapeHtml(tool.name)} · ${escapeHtml(tool.status)}</span>`).join("")}</div>`
      : "";
    const risk = message.risk ? `<p class="risk-note">${escapeHtml(message.risk)}</p>` : "";
    const controls = message.pendingAction
      ? `<div class="action-controls"><button class="confirm-button" data-confirm="${escapeHtml(message.pendingAction.id)}">确认并执行</button><button class="reject-button" data-reject="${escapeHtml(message.pendingAction.id)}">取消</button></div>`
      : "";
    const time = escapeHtml(message.time || "刚刚");
    return `<div class="message ${message.role === "user" ? "user-message" : "assistant-message"}"><p>${escapeHtml(message.text)}</p>${plan}${tools}${risk}${controls}<time>${time}</time></div>`;
  }).join("");
  container.scrollTop = container.scrollHeight;
}

function addMessage(role, text, result = {}) {
  messages.push({
    role,
    text,
    plan: result.plan || [],
    tools: result.tools || [],
    risk: result.pending_action?.risk || "",
    pendingAction: result.pending_action || null,
    time: new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date()),
  });
  renderMessages();
}

async function sendMessage(text) {
  const message = String(text || "").trim();
  if (!message || busy) return;
  addMessage("user", message);
  $("#chat-input").value = "";
  $("#suggestion-area").hidden = true;
  setBusy(true);
  try {
    const response = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    addMessage("assistant", response.reply, response);
    if (response.data || ["transfer", "scheduled_transfer", "split_aa", "birthday_bundle", "card_lock", "card_unlock", "card_limit", "card_daily_limit", "card_apply", "fund_purchase", "fund_redeem", "subscription_cancel", "subscription_reminder"].includes(response.intent)) {
      await loadState();
    }
  } catch (error) {
    addMessage("assistant", error.message);
    notify(error.message, true);
  } finally {
    setBusy(false);
    $("#chat-input").focus();
  }
}

function setBusy(value) {
  busy = value;
  const button = $('.send-button');
  button.disabled = value;
  button.textContent = value ? "…" : "↑";
}

async function handleAction(actionId, action) {
  if (busy) return;
  setBusy(true);
  try {
    const result = await api(`/api/actions/${actionId}/${action}`, {
      method: "POST",
      body: "{}",
    });
    messages.forEach((message) => {
      if (message.pendingAction?.id === actionId) message.pendingAction = null;
    });
    addMessage("assistant", result.message);
    if (result.state) {
      bankState = result.state;
      render();
    }
    notify(result.message);
  } catch (error) {
    messages.forEach((message) => {
      if (message.pendingAction?.id === actionId) message.pendingAction = null;
    });
    renderMessages();
    addMessage("assistant", error.message);
    notify(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function resetDemo() {
  if (!window.confirm("重置后会清除本次演示中的转账、预留和设置变更。继续吗？")) return;
  try {
    bankState = await api("/api/reset", { method: "POST", body: "{}" });
    messages = [];
    $("#suggestion-area").hidden = false;
    render();
    addMessage("assistant", "演示数据已重置。");
    notify("演示账户已重置");
  } catch (error) {
    notify(error.message, true);
  }
}

document.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    setView(viewButton.dataset.view);
    return;
  }
  const promptButton = event.target.closest("[data-prompt]");
  if (promptButton) {
    sendMessage(promptButton.dataset.prompt);
    return;
  }
  const confirmButton = event.target.closest("[data-confirm]");
  if (confirmButton) {
    handleAction(confirmButton.dataset.confirm, "confirm");
    return;
  }
  const rejectButton = event.target.closest("[data-reject]");
  if (rejectButton) {
    handleAction(rejectButton.dataset.reject, "reject");
    return;
  }
  if (event.target.closest('[data-action="reset"]')) {
    resetDemo();
    return;
  }
  if (event.target.closest('[data-action="clear-chat"]')) {
    messages = [];
    $("#suggestion-area").hidden = false;
    renderMessages();
    return;
  }
  if (event.target.closest('[data-action="notifications"]')) {
    const reminders = bankState?.reminders || [];
    notify(
      reminders.length
        ? `有 ${reminders.length} 条本地提醒：${reminders.map((item) => item.title).join("、")}`
        : "当前没有待处理提醒",
    );
  }
});

document.addEventListener("submit", (event) => {
  if (event.target.id !== "chat-form") return;
  event.preventDefault();
  sendMessage($("#chat-input").value);
});

$("#chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#chat-form").requestSubmit();
  }
});

loadState().catch((error) => {
  $("#main-content").innerHTML = `<div class="empty-state">${escapeHtml(error.message)} 请重新启动本地演示服务。</div>`;
  notify(error.message, true);
});

window.setInterval(async () => {
  try {
    bankState = await api(stateUrl);
    render();
  } catch {
    return;
  }
}, 15000);
