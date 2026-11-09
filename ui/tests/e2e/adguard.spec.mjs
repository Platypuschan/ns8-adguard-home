import { test, expect, configuration, status } from "./helpers.mjs";
const settingsHash = "#/apps/adguard-home1?page=settings";
async function settings(ns8) {
  const frame = await ns8.open({ hash: settingsHash });
  const task = await ns8.task("get-configuration");
  await ns8.complete("get-configuration", task.eventId, configuration);
  await expect(frame.locator("#adguard-url")).toHaveValue(configuration.url);
  return frame;
}
async function navigate(ns8, page) {
  await ns8.page.evaluate(
    (p) =>
      document
        .querySelector("#module")
        .contentWindow.dispatchEvent(
          new CustomEvent("changeRoute", { detail: p }),
        ),
    page,
  );
}
test("status renders services, images, volumes and host actions; about retains metadata", async ({
  ns8,
}) => {
  const frame = await ns8.open();
  const name = await ns8.task("get-name");
  expect(name.path).toBe("/module/adguard-home1/tasks");
  expect(name.headers.authorization).toBe("Bearer fixture-token");
  expect(name.payload.extra.eventId).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  await ns8.complete("get-name", name.eventId, { name: "Home DNS" });
  const st = await ns8.task("get-status");
  await ns8.complete("get-status", st.eventId, status);
  const repos = await ns8.task("list-backup-repositories");
  expect(repos.path).toBe("/cluster/tasks");
  await ns8.complete("list-backup-repositories", repos.eventId, {
    repositories: [],
  });
  const backups = await ns8.task("list-backups");
  await ns8.complete("list-backups", backups.eventId, { backups: [] });
  await expect(frame.getByText("Home DNS", { exact: true })).toBeVisible();
  await expect(frame.getByText("Node Alpha", { exact: true })).toBeVisible();
  await expect(
    frame.getByText("docker.io/adguard/adguardhome:fixture", { exact: true }),
  ).toBeVisible();
  await expect(frame.getByText("/config", { exact: true })).toBeVisible();
  await expect(frame.locator(".service-card")).toContainText("active");
  await frame.getByRole("button", { name: "Go to System logs" }).click();
  await frame
    .getByRole("button", { name: "Go to backup", exact: true })
    .click();
  expect(await ns8.pushed()).toContain(
    "/system-logs?context=module&selectedAppId=adguard-home1",
  );
  expect(await ns8.pushed()).toContain("/backup");
  await navigate(ns8, "about");
  const modules = await ns8.task("list-installed-modules");
  await ns8.complete("list-installed-modules", modules.eventId, {
    modules: [{ id: "adguard-home1", version: "0.1.99" }],
  });
  await expect(frame.getByText("0.1.99", { exact: true })).toBeVisible();
  await expect(
    frame.getByRole("link", {
      name: "https://github.com/Platypuschan/ns8-adguard-home",
      exact: true,
    }),
  ).toBeVisible();
  expect(ns8.problems).toEqual([]);
});
test("settings preserves credentials, DNS helpers, all payload fields and password omission", async ({
  ns8,
}) => {
  const frame = await settings(ns8);
  await expect(
    frame.getByRole("button", { name: "Save", exact: true }),
  ).toHaveAttribute("type", "submit");
  await expect(frame.locator("#adguard-admin-user")).toHaveValue("admin");
  await expect(frame.locator("#adguard-admin-password")).toHaveValue(
    "fixture-secret",
  );
  await expect(frame.locator("#adguard-admin-password")).toHaveAttribute(
    "type",
    "password",
  );
  await expect(frame.locator("#adguard-doh-url")).toHaveValue(
    configuration.doh_url,
  );
  await expect(frame.getByText(/192\.0\.2\.10/)).toBeVisible();
  await frame.getByPlaceholder("adguard.example.org").fill("dns.example.org");
  await frame
    .locator("#dns-bind-hosts")
    .fill("192.0.2.10, 2001:db8::1 127.0.0.1");
  await frame.locator("#new-admin-password").fill("new fixture password");
  await frame.locator("input[type=checkbox]").nth(0).uncheck({ force: true });
  await frame.locator("input[type=checkbox]").nth(1).uncheck({ force: true });
  await frame.getByRole("button", { name: "Save", exact: true }).click();
  const task = await ns8.task("configure-module");
  expect(task.payload.data).toEqual({
    host: "dns.example.org",
    lets_encrypt: false,
    http2https: false,
    dns_bind_hosts: ["192.0.2.10", "2001:db8::1", "127.0.0.1"],
    admin_password: "new fixture password",
  });
  expect(task.payload.extra.isNotificationHidden).toBe(false);
  await expect(
    frame.getByRole("button", { name: "Save", exact: true }),
  ).toBeDisabled();
  await ns8.complete("configure-module", task.eventId, {});
  const refresh = await ns8.task("get-configuration", { nth: 1 });
  await ns8.complete("get-configuration", refresh.eventId, configuration);
  await expect(frame.locator("#new-admin-password")).toHaveValue("");
  const baseline = ns8.requests.length;
  await ns8.complete("configure-module", task.eventId, {});
  await ns8.page.evaluate(
    () =>
      new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );
  expect(ns8.requests.length).toBe(baseline);
  await frame.getByRole("button", { name: "Save", exact: true }).click();
  const second = await ns8.task("configure-module", { nth: 1 });
  expect(second.payload.data).not.toHaveProperty("admin_password");
  expect(ns8.problems).toEqual([]);
});
test("client validation rejects empty host/DNS and passwords over 72 UTF8 bytes without save", async ({
  ns8,
}) => {
  const frame = await settings(ns8);
  await frame.getByPlaceholder("adguard.example.org").fill("");
  await frame.locator("#dns-bind-hosts").fill(" , ");
  await frame.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    frame.locator(".bx--form-requirement").filter({ hasText: "Required" }),
  ).toHaveCount(2);
  await frame.getByPlaceholder("adguard.example.org").fill("dns.example.org");
  await frame.locator("#dns-bind-hosts").fill("0.0.0.0");
  await frame.locator("#new-admin-password").fill("ä".repeat(37));
  await frame.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    frame.locator(".bx--form-requirement").filter({ hasText: /72/ }),
  ).toBeVisible();
  expect(
    ns8.requests.filter((r) => r.payload.action === "configure-module"),
  ).toHaveLength(0);
  expect(ns8.problems).toEqual([]);
});
test("server validation, aborted task and HTTP auth errors recover without stale subscriptions", async ({
  ns8,
}) => {
  const frame = await settings(ns8);
  await frame.getByRole("button", { name: "Save", exact: true }).click();
  let task = await ns8.task("configure-module");
  await ns8.validationFailed("configure-module", task.eventId, [
    { parameter: "host", error: "host_format" },
  ]);
  await expect(
    frame.getByRole("button", { name: "Save", exact: true }),
  ).toBeEnabled();
  expect(
    await ns8.page.evaluate(
      (id) => window.__fixtureListenerCount(id),
      task.eventId,
    ),
  ).toBe(0);
  await frame.getByRole("button", { name: "Save", exact: true }).click();
  task = await ns8.task("configure-module", { nth: 1 });
  await ns8.abort("configure-module", task.eventId);
  await expect(frame.getByRole("alert")).toBeVisible();
  expect(
    await ns8.page.evaluate(
      (id) => window.__fixtureListenerCount(id),
      task.eventId,
    ),
  ).toBe(0);
  ns8.setApi(() => ({ status: 403, body: "{}" }));
  await frame.getByRole("button", { name: "Save", exact: true }).click();
  task = await ns8.task("configure-module", { nth: 2 });
  await expect(
    frame.getByRole("button", { name: "Save", exact: true }),
  ).toBeEnabled();
  expect(
    await ns8.page.evaluate(
      (id) => window.__fixtureListenerCount(id),
      task.eventId,
    ),
  ).toBe(0);
  expect(ns8.problems).toEqual([]);
});
test.describe("German", () => {
  test.use({ locale: "de-DE" });
  test("settings render and submit with German labels without framework/i18n warnings", async ({
    ns8,
  }) => {
    const frame = await settings(ns8);
    await expect(
      frame.getByRole("heading", { name: "Einstellungen", exact: true }),
    ).toBeVisible();
    await frame.getByRole("button", { name: "Speichern", exact: true }).click();
    const task = await ns8.task("configure-module");
    expect(task.payload.data.host).toBe(configuration.host);
    expect(ns8.problems).toEqual([]);
  });
});

test("indexed DNS validation shows translated detail without translating it twice", async ({
  ns8,
}) => {
  const frame = await settings(ns8);
  await frame.getByRole("button", { name: "Save", exact: true }).click();
  const task = await ns8.task("configure-module");
  await ns8.validationFailed("configure-module", task.eventId, [
    {
      parameter: "dns_bind_hosts.1",
      error: "invalid_ip_address",
      value: "not-an-ip",
    },
  ]);
  await expect(
    frame
      .locator(".bx--form-requirement")
      .filter({ hasText: "Not a valid IP address: not-an-ip" }),
  ).toBeVisible();
  expect(ns8.problems).toEqual([]);
});

test("side menu and host history navigate all original pages and preserve hyphenated instance", async ({
  ns8,
}) => {
  const frame = await ns8.open();
  await frame
    .locator(".app-side-menu-content")
    .getByText("Settings", { exact: true })
    .click();
  await expect(
    frame.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await ns8.task("get-configuration");
  await expect(frame.locator("li.current-page")).toContainText("Settings");
  await frame
    .locator(".app-side-menu-content")
    .getByText("About", { exact: true })
    .click();
  await expect(
    frame.getByRole("heading", { name: "About", exact: true }),
  ).toBeVisible();
  await ns8.task("list-installed-modules");
  await ns8.page.evaluate(() => {
    location.hash = "#/apps/adguard-home1?page=status";
  });
  await expect(
    frame.getByRole("heading", { name: "Status", exact: true }),
  ).toBeVisible();
  expect(ns8.problems).toEqual([]);
});
