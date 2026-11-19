// AI 观点区：有观点才渲染，无观点保持恒等。
import { beforeEach, describe, expect, it } from "vitest";
import { renderReport } from "../src/views";
import type { ReportPayload } from "../src/types";
import { mount, verifyPayload } from "./fixtures";

const opinions = [
  {
    lane: "verify",
    subject: "shop.table:orders",
    opinion: "索引 idx_user_amount 疑似漏执行，可重放该语句补齐。",
    source: "ai",
    model: "qwen-plus",
    status: "ok",
    degraded_reason: null,
  },
  {
    lane: "lint",
    subject: "V02.sql:3",
    opinion: "",
    source: "ai",
    model: "qwen-plus",
    status: "degraded",
    degraded_reason: "unparsable reply (no JSON array)",
  },
];

function withOpinions(items?: unknown[]): ReportPayload {
  const data: Record<string, unknown> = { ...verifyPayload.data };
  if (items !== undefined) data.ai_opinions = items;
  return { ...verifyPayload, data } as ReportPayload;
}

beforeEach(() => {
  document.body.replaceChildren();
});

describe("ai opinions section", () => {
  it("renders lane, subject, model and degraded reason", () => {
    const root = mount();
    renderReport(root, withOpinions(opinions));
    const text = root.textContent ?? "";
    expect(text).toContain("AI 观点");
    expect(text).toContain("模型输出·未经实证·不影响退出码");
    expect(text).toContain("verify · shop.table:orders");
    expect(text).toContain("qwen-plus");
    expect(text).toContain("疑似漏执行");
    expect(text).toContain("降级");
    expect(text).toContain("unparsable reply (no JSON array)");
  });

  it("renders no opinions section when field missing or empty", () => {
    const plain = mount();
    renderReport(plain, withOpinions());
    expect(plain.textContent).not.toContain("AI 观点");

    const empty = mount();
    renderReport(empty, withOpinions([]));
    expect(empty.textContent).not.toContain("AI 观点");
  });
});
