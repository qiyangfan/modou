import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("报告壳层加载并渲染 verify 报告", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "墨斗报告" })).toBeVisible();
  const item = page.locator(".report-item").first();
  await expect(item).toHaveClass(/active/);
  await expect(page.locator("main")).not.toBeEmpty();
});

test("壳层无严重可访问性问题（axe WCAG 2.1 A/AA）", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".report-item").first()).toHaveClass(/active/);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const describe = (v: { id: string; nodes: { target: unknown[] }[] }) =>
    `${v.id}: ${v.nodes.map((n) => n.target.join(" > ")).join("; ")}`;
  const blocking = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  // 实测所有影响级别均为 0 条；任何新增违规（含 minor）都阻断，需要放宽时显式列出。
  const summary = blocking.map(describe).join(" | ");
  expect(summary, summary).toBe("");
  expect(results.violations.map(describe), "axe 全量违规").toEqual([]);
});
