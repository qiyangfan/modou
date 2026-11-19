// 综合巡检：三类信号的摘要与输入来源。
import { expect, it } from "vitest";
import { renderReport } from "../src/views";
import { mount, summaryPayload } from "./fixtures";

it("patrol summary view renders per-signal digests and input sources", () => {
  const root = mount();
  renderReport(root, summaryPayload);
  const text = root.textContent ?? "";
  expect(text).toContain("综合巡检");
  expect(text).toContain("退出码 1");
  expect(text).toContain("漂移");
  expect(text).toContain("新增 1");
  expect(text).toContain("定义变更 2");
  expect(text).toContain("确认未用 2");
  expect(text).toContain("冗余 1");
  expect(text).toContain("指纹榜 5");
  expect(text).toContain("user_id = ?");
  expect(text).toContain("shop.table:orders");
  expect(text).toContain("idx_dead");
  expect(text).toContain("drift.json");
  expect(text).toContain("slow.log.json");
});
