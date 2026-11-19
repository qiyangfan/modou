// 组件级测试：四类视图对样例报告的渲染断言（jsdom）
import { beforeEach, describe, expect, it } from "vitest";
import { renderReport } from "../src/views";
import {
  driftPayload,
  lintPayload,
  mount,
  optimizePayload,
  slowlogPayload,
  unusedPayload,
  verifyPayload,
} from "./fixtures";

beforeEach(() => {
  document.body.replaceChildren();
});

describe("core report views", () => {
  it("verify view renders conclusions grouped by db", () => {
    const root = mount();
    renderReport(root, verifyPayload);
    expect(root.textContent).toContain("变更验收");
    expect(root.textContent).toContain("库 shop");
    expect(root.textContent).toContain("漏执行");
    expect(root.textContent).toContain("idx_user_amount");
  });

  it("optimize view renders two-state suggestions only", () => {
    const root = mount();
    renderReport(root, optimizePayload);
    const text = root.textContent ?? "";
    expect(text).toContain("实测提升 87.8%");
    expect(text).toContain("未验证");
    expect(text).toContain("代价未降低");
    expect(text).toContain("采样口径声明");
  });

  it("lint view renders hits table", () => {
    const root = mount();
    renderReport(root, lintPayload);
    expect(root.textContent).toContain("CLA.015");
    expect(root.textContent).toContain("V01.sql:3");
  });
});

describe("patrol report views", () => {
  it("patrol drift view renders categories", () => {
    const root = mount();
    renderReport(root, driftPayload);
    expect(root.textContent).toContain("新增");
    expect(root.textContent).toContain("orders");
  });

  it("patrol unused view renders layered status and drop statement", () => {
    const root = mount();
    renderReport(root, unusedPayload);
    expect(root.textContent).toContain("确认未用");
    expect(root.textContent).toContain("DROP INDEX `idx_dead`");
  });

  it("patrol slowlog view renders fingerprint ranking", () => {
    const root = mount();
    renderReport(root, slowlogPayload);
    expect(root.textContent).toContain("次数 2");
    expect(root.textContent).toContain("user_id = ?");
  });
});
