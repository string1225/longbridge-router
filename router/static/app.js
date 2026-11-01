"use strict";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = { csrf: "", status: null, tokens: [], timer: null };
const base = new URL("./", location.href);
const date = (value) =>
  value
    ? new Date(value * 1000).toLocaleString("zh-CN", { hour12: false })
    : "尚未使用";
const errors = {
  invalid_password: "密码不正确",
  admin_login_required: "请重新登录管理台",
  csrf_invalid: "管理会话已更新，请重新登录",
  application_token_invalid: "应用 Token 无效或已失效",
  oauth_authorization_required: "请先连接长桥账户",
  oauth_reauthorization_required: "长桥授权已失效，请重新连接账户",
  oauth_refresh_token_missing: "缺少刷新凭证，请重新连接账户",
  upstream_timeout: "长桥服务请求超时",
  upstream_connection_failed: "无法连接长桥，请检查网络与代理",
  oauth_registration_failed: "长桥客户端注册失败，请检查网络后重试",
  oauth_token_exchange_failed: "长桥授权交换失败，请重新授权",
  rate_limited: "请求过于频繁，请稍后再试",
  disconnect_before_changing_oauth_region: "更换授权区域前需要先断开当前授权",
  invalid_request: "请检查输入内容与必选项",
  oauth_discovery_endpoint_mismatch: "长桥授权服务信息校验失败",
};
function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (error ? " error" : "");
  clearTimeout(state.timer);
  state.timer = setTimeout(
    () => el.classList.add("hidden"),
    error ? 7000 : 4000,
  );
}
async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.csrf) headers["X-CSRF-Token"] = state.csrf;
  const response = await fetch(new URL(path.replace(/^\//, ""), base), {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const result = await response.json();
  if (!response.ok) {
    const code = result.error?.code || "request_failed";
    if (response.status === 401 && path !== "admin/login" && state.csrf)
      showLogin();
    throw new Error(
      errors[code] ||
        `请求失败：${code}${result.request_id ? `（${result.request_id}）` : ""}`,
    );
  }
  return result;
}
function text(tag, value, className) {
  const el = document.createElement(tag);
  el.textContent = value;
  if (className) el.className = className;
  return el;
}
function badge(label, mode = "") {
  return text("span", label, "badge " + mode);
}
function showLogin(clearPassword = true) {
  state.csrf = "";
  $("#login-screen").classList.remove("hidden");
  $("#console").classList.add("hidden");
  if (clearPassword) $("#password").value = "";
}
function showConsole() {
  $("#login-screen").classList.add("hidden");
  $("#console").classList.remove("hidden");
  $("#password").value = "";
  $("#login-error").textContent = "";
  navigate();
}
const views = {
  overview: "服务概览",
  tokens: "应用 Token",
  activity: "调用与操作记录",
  develop: "开发接入",
  settings: "管理设置",
};
function navigate() {
  const view = views[location.hash.slice(1)]
    ? location.hash.slice(1)
    : "overview";
  $$(".view").forEach((el) =>
    el.classList.toggle("hidden", el.id !== "view-" + view),
  );
  $$("[data-view]").forEach((el) =>
    el.classList.toggle("active", el.dataset.view === view),
  );
  $("#breadcrumb").textContent = "管理台 / " + views[view];
  if (!state.csrf) return;
  if (view === "tokens") loadTokens().catch((e) => toast(e.message, true));
  if (view === "activity") loadEvents().catch((e) => toast(e.message, true));
}
function renderStatus(s) {
  state.status = s;
  const oauth = s.oauth;
  $("#metric-oauth").textContent = oauth.authorized ? "已连接" : "待授权";
  $("#metric-expiry").textContent = oauth.expires_at
    ? "到期 " + date(oauth.expires_at)
    : "连接账户后自动维护";
  $("#metric-tokens").textContent = s.active_tokens;
  $("#metric-requests").textContent = s.usage_24h.requests;
  $("#metric-errors").textContent = s.usage_24h.failures;
  const service = $("#service-badge");
  service.textContent = s.paused ? "应用访问已暂停" : "服务运行中";
  service.className = "badge" + (s.paused ? " warn" : "");
  $("#sidebar-status").textContent = s.paused
    ? "应用访问已暂停"
    : "服务正常运行";
  $("#pause-toggle").textContent = s.paused ? "恢复应用访问" : "暂停应用访问";
  $("#oauth-heading").textContent = oauth.authorized
    ? "长桥账户已连接"
    : "连接你的长桥账户";
  $("#oauth-description").textContent = oauth.authorized
    ? "服务器会在到期前自动刷新授权，应用无需处理长桥凭证。"
    : oauth.last_error
      ? "原授权已失效，需要重新完成网页授权。"
      : "完成一次网页授权，由服务器自动维护和刷新登录状态。";
  $("#oauth-start").textContent = oauth.authorized
    ? "重新授权"
    : "连接长桥账户";
  $("#oauth-refresh").disabled = !oauth.authorized;
  $("#oauth-disconnect").disabled = !oauth.client_registered;
  $("#updated-at").textContent =
    "更新于 " + new Date().toLocaleTimeString("zh-CN", { hour12: false });
  const routes = $("#route-rows");
  routes.replaceChildren();
  for (const [market, label] of [
    ["CN", "A 股"],
    ["HK", "港股"],
    ["US", "美股"],
  ]) {
    const tr = document.createElement("tr");
    const cell = document.createElement("td");
    const group = document.createElement("div");
    group.className = "market-name";
    group.append(text("span", market, "market-icon"), text("strong", label));
    cell.append(group);
    tr.append(cell);
    const endpoint = document.createElement("td");
    endpoint.append(text("code", s.routes[market].upstream));
    tr.append(endpoint);
    tr.append(text("td", market === "CN" ? "国内直连" : "VPN 代理"));
    const check = s.network?.markets?.[market];
    const statusCell = document.createElement("td");
    statusCell.append(
      check
        ? badge(
            check.reachable ? "连接正常" : "连接失败",
            check.reachable ? "" : "error",
          )
        : badge("尚未检测", "warn"),
    );
    tr.append(
      statusCell,
      text("td", check?.latency_ms != null ? check.latency_ms + " ms" : "—"),
    );
    routes.append(tr);
  }
  if (s.network?.checked_at)
    $("#network-note").textContent =
      "上次检查：" +
      date(s.network.checked_at) +
      "。网络可达不代表账户具备实时行情权限。";
  const url = s.public_url;
  $("#env-example").textContent =
    `LONGBRIDGE_ROUTER_URL=${url}\nLONGBRIDGE_ROUTER_TOKEN=<你的应用 Token>`;
  $("#curl-example").textContent =
    `curl --get '${url}/v1/quotes' \\\n  --data-urlencode 'symbols=600519.SH,700.HK,AAPL.US' \\\n  -H "Authorization: Bearer $LONGBRIDGE_ROUTER_TOKEN"`;
}
async function refreshStatus() {
  renderStatus(await api("admin/status"));
}
async function loadTokens() {
  state.tokens = (await api("admin/tokens")).tokens;
  renderTokens();
}
function renderTokens() {
  const rows = $("#token-rows");
  rows.replaceChildren();
  const filter = $("#token-filter").value.toLowerCase();
  const tokens = state.tokens.filter(
    (t) =>
      t.name.toLowerCase().includes(filter) &&
      ($("#show-inactive").checked ||
        (!t.revoked && t.expires_at > Date.now() / 1000)),
  );
  $("#token-empty").classList.toggle("hidden", tokens.length !== 0);
  for (const token of tokens) {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    name.append(text("strong", token.name), text("small", token.prefix + "…"));
    const grants = document.createElement("td");
    grants.append(
      text("span", token.markets.join(" / ")),
      text("small", token.scopes.join(" · ")),
    );
    tr.append(
      name,
      grants,
      text("td", token.rate_limit + " / 分钟"),
      text("td", date(token.expires_at)),
    );
    const used = document.createElement("td");
    used.append(
      text("span", date(token.last_used)),
      text("small", "累计 " + token.uses + " 次"),
    );
    tr.append(used);
    const actions = document.createElement("td");
    const buttons = document.createElement("div");
    buttons.className = "row-actions";
    if (!token.revoked && token.expires_at > Date.now() / 1000) {
      for (const [label, action] of [
        ["轮换", "rotate"],
        ["撤销", "revoke"],
      ]) {
        const button = text(
          "button",
          label,
          action === "revoke" ? "danger-secondary" : "subtle",
        );
        button.type = "button";
        button.addEventListener("click", () => tokenAction(token, action));
        buttons.append(button);
      }
    } else buttons.append(badge(token.revoked ? "已撤销" : "已过期", "warn"));
    actions.append(buttons);
    tr.append(actions);
    rows.append(tr);
  }
}
function showSecret(token) {
  $("#token-secret").value = token;
  $("#secret-dialog").showModal();
}
async function tokenAction(token, action) {
  if (
    !confirm(
      `${action === "rotate" ? "轮换" : "撤销"}「${token.name}」？现有 Token 会立即失效。`,
    )
  )
    return;
  try {
    const result = await api(
      "admin/tokens/" + token.id + (action === "rotate" ? "/rotate" : ""),
      { method: action === "rotate" ? "POST" : "DELETE" },
    );
    if (action === "rotate") showSecret(result.token);
    else toast("应用 Token 已撤销");
    await Promise.all([loadTokens(), refreshStatus()]);
  } catch (error) {
    toast(error.message, true);
  }
}
async function loadEvents() {
  const data = await api("admin/events");
  const rows = $("#event-rows");
  rows.replaceChildren();
  for (const event of data.events) {
    const tr = document.createElement("tr");
    const label =
      event.actor === "admin"
        ? "管理员"
        : event.actor === "system"
          ? "系统"
          : event.actor === "anonymous"
            ? "未登录"
            : state.tokens.find((t) => t.id === event.actor)?.name ||
              event.actor.slice(0, 10);
    tr.append(
      text("td", date(event.created_at)),
      text("td", label),
      text("td", event.action),
      text("td", event.market || "—"),
    );
    const status = document.createElement("td");
    status.append(badge(event.status, event.status >= 400 ? "error" : ""));
    tr.append(
      status,
      text("td", event.duration_ms != null ? event.duration_ms + " ms" : "—"),
    );
    rows.append(tr);
  }
}
async function busy(button, work) {
  button.disabled = true;
  try {
    await work();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}
$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  try {
    const result = await api("admin/login", {
      method: "POST",
      body: JSON.stringify({ password: $("#password").value }),
    });
    state.csrf = result.csrf_token;
    await refreshStatus();
    await loadTokens();
    showConsole();
  } catch (error) {
    $("#login-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
$("#logout").addEventListener("click", (event) =>
  busy(event.currentTarget, async () => {
    await api("admin/logout", { method: "POST" });
    showLogin();
  }),
);
$("#refresh").addEventListener("click", (event) =>
  busy(event.currentTarget, async () => {
    await refreshStatus();
    navigate();
    toast("状态已更新");
  }),
);
$("#refresh-events").addEventListener("click", (event) =>
  busy(event.currentTarget, loadEvents),
);
$("#network-check").addEventListener("click", (event) =>
  busy(event.currentTarget, async () => {
    toast("正在检查国内直连与海外代理…");
    await api("admin/network/check", { method: "POST" });
    await refreshStatus();
    toast("网络检查已完成");
  }),
);
$("#oauth-start").addEventListener("click", (event) =>
  busy(event.currentTarget, async () => {
    const result = await api("admin/oauth/start", {
      method: "POST",
      body: JSON.stringify({ region: state.status.oauth.region || "global" }),
    });
    location.assign(result.authorization_url);
  }),
);
$("#oauth-refresh").addEventListener("click", (event) =>
  busy(event.currentTarget, async () => {
    await api("admin/oauth/refresh", { method: "POST" });
    await refreshStatus();
    toast("长桥授权已刷新");
  }),
);
$("#oauth-disconnect").addEventListener("click", (event) => {
  if (confirm("断开长桥授权？所有应用的数据读取将暂停，直到重新授权。"))
    busy(event.currentTarget, async () => {
      await api("admin/oauth", { method: "DELETE" });
      await refreshStatus();
      toast("已删除本服务保存的长桥授权");
    });
});
$("#pause-toggle").addEventListener("click", (event) =>
  busy(event.currentTarget, async () => {
    await api("admin/control", {
      method: "POST",
      body: JSON.stringify({ paused: !state.status.paused }),
    });
    await refreshStatus();
    toast(state.status.paused ? "已暂停应用访问" : "已恢复应用访问");
  }),
);
for (const id of ["#new-token", "#new-token-empty"])
  $(id).addEventListener("click", () => {
    $("#token-form").reset();
    $("#token-dialog").showModal();
  });
$(".close-dialog").addEventListener("click", () => $("#token-dialog").close());
$("#token-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  const markets = $$("input[name=markets]:checked").map((el) => el.value);
  const scopes = $$("input[name=scopes]:checked").map((el) => el.value);
  if (!markets.length || !scopes.length)
    return toast("至少选择一个市场和一项读取权限", true);
  busy(button, async () => {
    const result = await api("admin/tokens", {
      method: "POST",
      body: JSON.stringify({
        name: $("#token-name").value.trim(),
        markets,
        scopes,
        rate_limit: Number($("#token-rate").value),
        expires_days: Number($("#token-days").value),
      }),
    });
    $("#token-dialog").close();
    showSecret(result.token);
    await Promise.all([loadTokens(), refreshStatus()]);
  });
});
$("#token-filter").addEventListener("input", renderTokens);
$("#show-inactive").addEventListener("change", renderTokens);
$("#secret-close").addEventListener("click", () => {
  $("#token-secret").value = "";
  $("#secret-dialog").close();
});
$("#secret-dialog").addEventListener("close", () => {
  $("#token-secret").value = "";
});
$("#copy-token").addEventListener("click", (event) =>
  busy(event.currentTarget, async () => {
    await navigator.clipboard.writeText($("#token-secret").value);
    toast("Token 已复制");
  }),
);
$("#password-form").addEventListener("submit", (event) => {
  event.preventDefault();
  busy(event.currentTarget.querySelector("button"), async () => {
    await api("admin/password", {
      method: "POST",
      body: JSON.stringify({
        current_password: $("#current-password").value,
        new_password: $("#new-password").value,
      }),
    });
    $("#password-form").reset();
    showLogin();
    toast("密码已更新，请使用新密码登录");
  });
});
window.addEventListener("hashchange", navigate);
(async () => {
  try {
    state.csrf = (await api("admin/session")).csrf_token;
    await Promise.all([refreshStatus(), loadTokens()]);
    showConsole();
  } catch {
    showLogin(false);
  } finally {
    const button = $("#login-form button");
    button.disabled = false;
    button.textContent = "登录管理台";
  }
})();
