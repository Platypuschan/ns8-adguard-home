import { test, expect, configuration } from "./helpers.mjs";
test("navigating away disposes outstanding task listeners", async ({ ns8 }) => {
  const frame = await ns8.open({ hash: "#/apps/adguard-home1?page=settings" });
  const config = await ns8.task("get-configuration");
  await ns8.page.evaluate(() =>
    document
      .querySelector("#module")
      .contentWindow.dispatchEvent(
        new CustomEvent("changeRoute", { detail: "about" }),
      ),
  );
  await expect(
    frame.getByRole("heading", { name: "About", exact: true }),
  ).toBeVisible();
  await ns8.complete("get-configuration", config.eventId, configuration);
  expect(
    await ns8.page.evaluate(() => Object.keys(window.__handlers || {})),
  ).toEqual([]);
  expect(
    await ns8.page.evaluate(
      (id) => window.__fixtureListenerCount(id),
      config.eventId,
    ),
  ).toBe(0);
  expect(ns8.problems).toEqual([]);
});
