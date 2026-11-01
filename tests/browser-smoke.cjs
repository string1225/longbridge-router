/* Live smoke test. No upstream account data or credentials are printed. */
const fs = require("node:fs");
const assert = require("node:assert/strict");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = (
  process.env.ROUTER_TEST_URL || "https://home.sunny-string.cn/longbridge"
).replace(/\/$/, "");
const file = process.env.ROUTER_ADMIN_CREDENTIAL_FILE;
if (!file)
  throw new Error(
    "Set ROUTER_ADMIN_CREDENTIAL_FILE to the private bootstrap handoff",
  );
const password = fs
  .readFileSync(file, "utf8")
  .match(/管理员初始密码：([^\r\n]+)/)?.[1];
if (!password) throw new Error("Password not found in credential handoff");
const output = path.resolve("artifacts");
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    channel: "msedge",
    headless: true,
    args: ["--no-proxy-server"],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1024 },
  });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (e) => runtimeErrors.push(e.message));
  let paused = false;
  let csrf = "";
  let created = [];
  try {
    assert.equal((await page.goto(base + "/")).status(), 200);
    await page.locator("#password").fill(password);
    await page.locator("#login-form button").click();
    await page.locator("#console:not(.hidden)").waitFor();
    const session = await context.request.get(base + "/admin/session");
    csrf = (await session.json()).csrf_token;
    const admin = { "X-CSRF-Token": csrf, Origin: new URL(base).origin };
    assert.equal(
      (await context.request.get(base + "/admin/status")).status(),
      200,
    );

    await page.locator("#network-check").click();
    await page.waitForFunction(
      () => !document.querySelector("#network-check").disabled,
      { timeout: 65000 },
    );
    assert.equal(
      await page.locator("#route-rows").getByText("连接正常").count(),
      3,
    );
    await page.screenshot({
      path: path.join(output, "overview-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await page.screenshot({
      path: path.join(output, "overview-mobile.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 1440, height: 1024 });

    await page.locator('nav a[href="#tokens"]').click();
    await page.locator("#new-token").click();
    const name = "qa-browser-" + Date.now();
    await page.locator("#token-name").fill(name);
    await page.locator("#token-form button[type=submit]").click();
    await page.locator("#secret-dialog[open]").waitFor();
    const original = await page.locator("#token-secret").inputValue();
    assert.ok(original.startsWith("lbr_"));
    await page.locator("#secret-close").click();
    await page.waitForFunction(
      () => document.querySelector("#token-secret").value === "",
    );
    let row = page.locator("#token-rows tr").filter({ hasText: name });
    await row.waitFor();
    const listing = await (
      await context.request.get(base + "/admin/tokens")
    ).json();
    created = listing.tokens.filter((t) => t.name === name).map((t) => t.id);
    assert.ok(!JSON.stringify(listing).includes(original));
    const consumer = (token) => ({ Authorization: "Bearer " + token });
    assert.equal(
      (
        await context.request.get(base + "/v1/status", {
          headers: consumer(original),
        })
      ).status(),
      200,
    );
    const helper = spawnSync(
      process.env.PYTHON || "python",
      ["skills/longbridge-router/scripts/client.py", "status"],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          LONGBRIDGE_ROUTER_URL: base,
          LONGBRIDGE_ROUTER_TOKEN: original,
        },
      },
    );
    assert.ok(
      helper.status === 0,
      "Distributed skill client must call the live status endpoint",
    );
    assert.ok(JSON.parse(helper.stdout).data.markets.includes("CN"));
    assert.equal(
      (
        await context.request.get(base + "/v1/quotes?symbols=700.HK", {
          headers: consumer(original),
        })
      ).status(),
      409,
    );

    page.once("dialog", (d) => d.accept());
    await row.getByRole("button", { name: "轮换", exact: true }).click();
    await page.locator("#secret-dialog[open]").waitFor();
    const rotated = await page.locator("#token-secret").inputValue();
    await page.locator("#secret-close").click();
    assert.ok(
      original !== rotated,
      "Rotation must issue a different credential",
    );
    assert.equal(
      (
        await context.request.get(base + "/v1/status", {
          headers: consumer(original),
        })
      ).status(),
      401,
    );
    assert.equal(
      (
        await context.request.get(base + "/v1/status", {
          headers: consumer(rotated),
        })
      ).status(),
      200,
    );

    await page.locator('nav a[href="#settings"]').click();
    await page.locator("#pause-toggle").click();
    await page
      .getByRole("button", { name: "恢复应用访问", exact: true })
      .waitFor();
    paused = true;
    assert.equal(
      (
        await context.request.get(base + "/v1/quotes?symbols=700.HK", {
          headers: consumer(rotated),
        })
      ).status(),
      503,
    );
    await page.locator("#pause-toggle").click();
    await page
      .getByRole("button", { name: "暂停应用访问", exact: true })
      .waitFor();
    paused = false;

    await page.locator('nav a[href="#tokens"]').click();
    row = page.locator("#token-rows tr").filter({ hasText: name });
    page.once("dialog", (d) => d.accept());
    await row.getByRole("button", { name: "撤销", exact: true }).click();
    await row.waitFor({ state: "hidden" });
    assert.equal(
      (
        await context.request.get(base + "/v1/status", {
          headers: consumer(rotated),
        })
      ).status(),
      401,
    );
    await page.locator("#show-inactive").check();
    assert.equal(
      await page.locator("#token-rows tr").filter({ hasText: name }).count(),
      2,
    );
    await page.screenshot({
      path: path.join(output, "tokens-desktop.png"),
      fullPage: true,
    });

    await page.locator('nav a[href="#activity"]').click();
    await page.locator("#event-rows tr").first().waitFor();
    await page.locator('nav a[href="#develop"]').click();
    const bundle = await context.request.get(base + "/admin/skill-bundle");
    assert.equal(bundle.status(), 200);
    assert.equal((await bundle.body()).subarray(0, 2).toString(), "PK");
    const spec = await (
      await context.request.get(base + "/openapi.json")
    ).json();
    assert.ok(spec.paths["/v1/quotes"]);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await page.screenshot({
      path: path.join(output, "develop-mobile.png"),
      fullPage: true,
    });
    const authorization = await context.request.post(
      base + "/admin/oauth/start",
      { headers: admin, data: { region: "global" } },
    );
    assert.equal(authorization.status(), 200);
    const url = new URL((await authorization.json()).authorization_url);
    assert.equal(url.origin, "https://openapi.longbridge.com");
    assert.equal(url.searchParams.get("code_challenge_method"), "S256");
    assert.equal(
      url.searchParams.get("redirect_uri"),
      base + "/oauth/callback",
    );
    assert.deepEqual(runtimeErrors, []);
    console.log(
      JSON.stringify({
        result: "PASS",
        desktop: "1440x1024",
        mobile: "390x844",
        network: ["CN", "HK", "US"],
        flows: [
          "login",
          "network",
          "create",
          "rotate",
          "revoke",
          "pause",
          "resume",
          "audit",
          "skill-download",
          "openapi",
          "oauth-registration-pkce",
        ],
        accountData: "awaiting owner consent",
        runtimeErrors,
      }),
    );
    await page.locator("#logout").click();
    await page.locator("#login-screen:not(.hidden)").waitFor();
  } catch (error) {
    console.error(
      JSON.stringify(
        await page.evaluate(() => ({
          url: location.pathname,
          hash: location.hash,
          views: [...document.querySelectorAll(".view")].map((e) => ({
            id: e.id,
            hidden: e.classList.contains("hidden"),
          })),
          loginError: document.querySelector("#login-error").textContent,
        })),
      ),
    );
    await page.screenshot({
      path: path.join(output, "browser-failure.png"),
      fullPage: true,
    });
    throw error;
  } finally {
    const admin = { "X-CSRF-Token": csrf };
    if (paused)
      await context.request.post(base + "/admin/control", {
        headers: admin,
        data: { paused: false },
      });
    if (csrf) {
      const response = await context.request.get(base + "/admin/tokens");
      if (response.ok()) {
        for (const t of (await response.json()).tokens.filter(
          (t) => t.name.startsWith("qa-browser-") && !t.revoked,
        ))
          await context.request.delete(base + "/admin/tokens/" + t.id, {
            headers: admin,
          });
      }
    }
    await browser.close();
  }
})().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
