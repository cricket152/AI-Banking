"use strict";

Object.assign(state, {
  report: null,
  reportRange: null,
  reportRevision: 0,
  subscriptionCandidates: [],
  candidateConfirmation: null,
});

Object.assign(errors, {
  INVALID_DATE_RANGE: "日期范围无效，请选择不超过 366 天的区间。",
  SUBSCRIPTION_EVIDENCE_CHANGED:
    "扣费证据已变化或已登记。请关闭确认单并刷新后重新核对。",
});

function resetInsights() {
  state.report = null;
  state.reportRange = null;
  state.reportRevision += 1;
  state.subscriptionCandidates = [];
  state.candidateConfirmation = null;
  $("#subscription-dialog").close();
  $("#subscription-candidates").replaceChildren();
  $("#insights-result").replaceChildren();
  $("#insights-status").textContent = "";
  $("#insights-section").removeAttribute("aria-busy");
  $("#insights-submit").disabled = false;
}

function isoDate(value) {
  return value.toISOString().slice(0, 10);
}

function reportPreset(preset) {
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const [year, month, day] = today.split("-").map(Number);
  let start = new Date(Date.UTC(year, month - 1, 1));
  let end = new Date(Date.UTC(year, month - 1, day));
  if (preset === "last-month") {
    start = new Date(Date.UTC(year, month - 2, 1));
    end = new Date(Date.UTC(year, month - 1, 0));
  } else if (preset === "year") start = new Date(Date.UTC(year, 0, 1));
  $("#insights-start").value = isoDate(start);
  $("#insights-end").value = isoDate(end);
}

async function loadInsights() {
  if (!state.user) return;
  if (!$("#insights-start").value) reportPreset("month");
  const start = $("#insights-start").value;
  const inclusiveEnd = $("#insights-end").value;
  const endDate = new Date(`${inclusiveEnd}T00:00:00Z`);
  endDate.setUTCDate(endDate.getUTCDate() + 1);
  if (
    !start ||
    !inclusiveEnd ||
    !Number.isFinite(endDate.getTime()) ||
    start > inclusiveEnd
  ) {
    $("#insights-status").textContent = "请填写有效的开始和结束日期。";
    return;
  }
  const revision = ++state.reportRevision,
    user = state.user;
  state.report = null;
  state.reportRange = { start, end: isoDate(endDate) };
  $("#insights-result").replaceChildren();
  $("#insights-status").textContent = "正在读取完整区间账单…";
  $("#insights-section").setAttribute("aria-busy", "true");
  $("#insights-submit").disabled = true;
  try {
    const report = await api(
      `/api/bank/reports?${new URLSearchParams(state.reportRange)}`,
    );
    if (state.user !== user || state.reportRevision !== revision) return;
    state.report = report;
    renderInsights();
    $("#insights-status").textContent =
      `统计 ${report.start_inclusive} 至 ${inclusiveEnd}（东八区），共 ${report.entry_ids.length} 笔流水。`;
  } catch (error) {
    if (state.user === user && state.reportRevision === revision)
      $("#insights-status").textContent = error.message;
  } finally {
    if (state.user === user && state.reportRevision === revision) {
      $("#insights-submit").disabled = false;
      $("#insights-section").removeAttribute("aria-busy");
    }
  }
}

function evidenceTable(entries) {
  const wrap = element("div", "table-scroll");
  const table = element("table", "evidence-table");
  const head = element("thead"),
    heading = element("tr");
  for (const label of ["商户 / 分类", "日期（东八区）", "金额"]) {
    const cell = element("th", "", label);
    cell.scope = "col";
    heading.append(cell);
  }
  head.append(heading);
  const body = element("tbody");
  for (const entry of entries) {
    const row = element("tr");
    row.append(
      element("td", "", `${entry.merchant} · ${entry.category}`),
      element(
        "td",
        "",
        new Date(entry.happened_at).toLocaleString("zh-CN", {
          timeZone: "Asia/Shanghai",
        }),
      ),
      element("td", "", currency(entry.amount_minor)),
    );
    body.append(row);
  }
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

function reportEvidence(label, filter = {}, sourceRange = state.reportRange) {
  const details = element("details", "insights-evidence");
  details.append(element("summary", "", label));
  const content = element("div"),
    more = element("button", "button secondary", "加载更多");
  more.type = "button";
  let offset = 0,
    loaded = false,
    busy = false;
  const revision = state.reportRevision,
    user = state.user,
    range = { ...sourceRange };
  const load = async () => {
    if (busy || offset === null || !state.user) return;
    busy = true;
    more.disabled = true;
    try {
      const page = await api(
        `/api/bank/reports/entries?${new URLSearchParams({ ...range, ...filter, offset, limit: 20 })}`,
      );
      if (
        state.user !== user ||
        state.reportRevision !== revision ||
        !details.isConnected
      )
        return;
      if (!loaded) content.replaceChildren();
      if (!page.total)
        content.append(element("p", "muted", "该范围没有流水。"));
      else content.append(evidenceTable(page.entries));
      loaded = true;
      offset = page.next_offset;
      more.hidden = offset === null;
    } catch (error) {
      if (state.user === user && state.reportRevision === revision)
        content.append(element("p", "error", error.message));
    } finally {
      busy = false;
      more.disabled = false;
    }
  };
  details.addEventListener("toggle", () => {
    if (details.open && !loaded) load();
  });
  more.addEventListener("click", load);
  details.append(content, more);
  return details;
}

function renderInsights() {
  const target = $("#insights-result"),
    report = state.report;
  target.replaceChildren();
  if (!report || !state.user) return;
  const metrics = element("div", "insights-metrics");
  for (const [label, value] of [
    ["消费支出", report.expense_minor],
    ["退款", report.refund_minor],
    ["净支出", report.net_expense_minor],
    ["收入", report.income_minor],
  ]) {
    const card = element("article", "insights-metric");
    card.append(
      element("span", "muted", label),
      element("strong", "", currency(value)),
    );
    metrics.append(card);
  }
  const comparison = report.comparison;
  target.append(
    metrics,
    element(
      "p",
      "muted",
      `消费不含转账；转入 ${currency(report.transfer_in_minor)}，转出 ${currency(report.transfer_out_minor)}。退款单列，不回溯修改原消费分类。`,
    ),
    element("h3", "insights-subtitle", "分类与时间对比"),
    element(
      "p",
      "muted",
      `对比 ${comparison.start_inclusive} 至 ${comparison.end_exclusive}（结束日不含）的前一等长区间。${comparison.entry_count ? `消费支出变化 ${currency(comparison.expense_delta_minor)}。` : "对比区间暂无流水，无法据此判断消费增长或节省。"}`,
    ),
  );
  if (!comparison.by_category.length)
    target.append(element("p", "empty", "这个区间没有消费支出。"));
  for (const category of comparison.by_category) {
    const card = element("article", "insights-category");
    card.append(
      element("strong", "", category.category),
      element(
        "p",
        "",
        `本期 ${currency(category.current_minor)} · 前期 ${currency(category.previous_minor)} · 变化 ${currency(category.delta_minor)}`,
      ),
      reportEvidence("展开本期分类流水", { category: category.category }),
      reportEvidence(
        "展开前期分类流水",
        { category: category.category },
        {
          start: comparison.start_inclusive,
          end: comparison.end_exclusive,
        },
      ),
    );
    target.append(card);
  }
  target.append(
    element("h3", "insights-subtitle", "需要你核对的支出"),
    element(
      "p",
      "muted",
      "以下仅是规则发现的线索，不是欺诈结论；正常消费也可能触发。",
    ),
  );
  if (!report.possible_anomalies.length)
    target.append(
      element("p", "muted", "未触发当前规则；这不代表所有交易均无异常。"),
    );
  for (const anomaly of report.possible_anomalies) {
    const card = element("article", "insights-category");
    card.append(
      element(
        "strong",
        "",
        `${anomaly.merchant} · ${currency(anomaly.amount_minor)}`,
      ),
      element("p", "", anomaly.reason),
    );
    if (anomaly.baseline_minor !== undefined)
      card.append(
        element(
          "p",
          "muted",
          `前期同类 ${anomaly.baseline_count} 笔，中位数 ${currency(anomaly.baseline_minor)}。`,
        ),
      );
    card.append(reportEvidence("核对这笔流水", { entry_id: anomaly.entry_id }));
    target.append(card);
  }
  target.append(reportEvidence("展开全部区间流水（含收入、退款和转账）"));
}

function candidateEvidence(candidate) {
  const content = element("div");
  content.append(
    element("strong", "", candidate.merchant),
    element(
      "p",
      "",
      `${bankAccountLabel(candidate.account_id)} · 每次 ${currency(candidate.amount_minor)} · ${candidate.charge_count} 次`,
    ),
    element("p", "muted", candidate.reason),
    element(
      "p",
      "muted",
      `预计下次日期 ${new Date(candidate.estimated_next_charge_at).toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai" })}${candidate.estimate_overdue ? "（已过估计日期，请核对）" : ""}。${candidate.note}`,
    ),
    evidenceTable(candidate.evidence),
  );
  return content;
}

function renderSubscriptionCandidates() {
  const target = $("#subscription-candidates");
  target.replaceChildren();
  for (const candidate of state.subscriptionCandidates) {
    const card = element("article", "operation-card");
    const details = element("details", "insights-evidence");
    details.append(
      element(
        "summary",
        "",
        `${candidate.merchant} · ${currency(candidate.amount_minor)} / 月度线索`,
      ),
      candidateEvidence(candidate),
    );
    card.append(
      details,
      bankButton("核对并登记", () => {
        state.candidateConfirmation = candidate;
        $("#subscription-dialog-content").replaceChildren(
          candidateEvidence(candidate),
        );
        $("#subscription-acknowledged").checked = false;
        $("#subscription-confirm").disabled = true;
        $("#subscription-dialog-error").textContent = "";
        $("#subscription-dialog").showModal();
      }),
    );
    target.append(card);
  }
  if (!state.subscriptionCandidates.length)
    target.append(
      element(
        "p",
        "muted",
        "暂无符合规则的疑似订阅。至少需要同商户三次等额月度支出；记录不足不代表没有订阅。",
      ),
    );
}

$("#insights-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadInsights();
});
document.querySelectorAll("[data-report-preset]").forEach((button) =>
  button.addEventListener("click", () => {
    reportPreset(button.dataset.reportPreset);
    loadInsights();
  }),
);
$("#subscription-acknowledged").addEventListener("change", () => {
  $("#subscription-confirm").disabled =
    !$("#subscription-acknowledged").checked || state.bankBusy;
});
$("#subscription-dialog-close").addEventListener("click", () => {
  if (!state.bankBusy) $("#subscription-dialog").close();
});
$("#subscription-dialog").addEventListener("cancel", (event) => {
  if (state.bankBusy) event.preventDefault();
});
$("#subscription-confirm").addEventListener("click", () => {
  if (!$("#subscription-acknowledged").checked || !state.candidateConfirmation)
    return;
  const candidate = state.candidateConfirmation;
  runBank(async (user) => {
    $("#subscription-confirm").disabled = true;
    try {
      await api(
        `/api/bank/subscriptions/candidates/${candidate.candidate_id}/confirm`,
        {
          method: "POST",
          body: JSON.stringify({
            evidence_digest: candidate.evidence_digest,
            acknowledged: true,
          }),
        },
      );
      if (state.user !== user) return;
      $("#subscription-dialog").close();
      state.candidateConfirmation = null;
      await loadBankData();
      bankMessage("已登记订阅，未扣款。取消订阅仍需单独确认或明确预授权。");
    } catch (error) {
      if (state.user === user)
        $("#subscription-dialog-error").textContent = error.message;
    } finally {
      $("#subscription-confirm").disabled = true;
      $("#subscription-acknowledged").checked = false;
    }
  });
});
