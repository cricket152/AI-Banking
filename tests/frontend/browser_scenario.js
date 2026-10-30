"use strict";

const waitFor = async (condition, label) => {
  for (let attempt = 0; attempt < 400; attempt += 1) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`等待超时：${label}`);
};

window.addEventListener(
  "load",
  async () => {
    const root = document.documentElement;
    try {
      await waitFor(
        () => document.querySelector("#today")?.textContent,
        "应用启动",
      );
      document.querySelector("#username").value = "browser_smoke";
      document.querySelector("#password").value = "browser-test-only-password";
      document.querySelector("#login-submit").click();

      await waitFor(
        () =>
          !document.querySelector("#workspace").hidden &&
          document.querySelector("#profile-name").textContent === "browser_smoke",
        "登录完成",
      );
      await waitFor(
        () =>
          document.querySelector("#accounts-list .account-card") &&
          document.querySelector("#total-balance").textContent !== "—",
        "账户数据加载",
      );

      const accountsNavigation = document.querySelector('nav button[data-page="accounts"]');
      if (!accountsNavigation) throw new Error("找不到“我的账户”导航按钮");
      accountsNavigation.click();
      await waitFor(
        () =>
          document.querySelector("#breadcrumb").textContent === "我的账户" &&
          !document.querySelector("#accounts-section").hidden &&
          accountsNavigation.getAttribute("aria-current") === "page",
        "账户页导航",
      );

      const accountNames = document.querySelector("#accounts-list").textContent;
      if (!accountNames.includes("日常账户") || !accountNames.includes("储蓄账户")) {
        throw new Error("账户页未显示预期的模拟账户");
      }
      root.dataset.frontendTest = "passed";
      root.dataset.frontendTestPath = "login-to-accounts";
    } catch (error) {
      root.dataset.frontendTest = "failed";
      root.dataset.frontendTestError = String(error?.message || error).replace(/[\r\n]/g, " ");
    }
  },
  { once: true },
);
