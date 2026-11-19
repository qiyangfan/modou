// 回归：失败报告与边界形态不得误报「一致」或白屏。
import { beforeEach, expect, it } from "vitest";
import { renderReport } from "../src/views";
import type { ReportPayload } from "../src/types";
import { mount, optimizePayload, verifyPayload } from "./fixtures";

beforeEach(() => {
  document.body.replaceChildren();
});

function verifyPayloadWith(exitCode: number): ReportPayload {
  return {
    id: "v",
    kind: "verify",
    version: 1,
    source: "v.json",
    data: {
      report_version: 1,
      exit_code: exitCode,
      summary: {
        missing_execution: 0,
        wrong_execution: 0,
        historical_drift: 0,
      },
      env_errors: [],
      databases: {},
    },
  };
}

it("exit-2 verify with empty databases never claims 全部一致", () => {
  const root = mount();
  const payload = verifyPayloadWith(2);
  payload.data.env_errors = ["shadow container failed: image not found"];
  renderReport(root, payload);
  const text = root.textContent ?? "";
  expect(text).toContain("环境/输入错误");
  expect(text).not.toContain("全部一致");
});

it("clean empty verify still claims 全部一致", () => {
  const root = mount();
  renderReport(root, verifyPayloadWith(0));
  expect(root.textContent).toContain("全部一致");
});

it("exit_code 1 with empty databases never claims 全部一致", () => {
  const root = mount();
  renderReport(root, verifyPayloadWith(1));
  expect(root.textContent).not.toContain("全部一致");
});

it("malformed payload renders error card instead of crashing", () => {
  // 各 renderer 已做 ?? 缺省；能击穿防御的只剩类型错位（数字字段给成字符串）
  const root = mount();
  renderReport(root, {
    id: "bad",
    kind: "patrol_slowlog",
    version: 1,
    source: "bad.json",
    data: {
      entries_parsed: 1,
      top: [
        {
          count: 1,
          query_time_total: "oops",
          query_time_max: 1,
          rows_examined_total: 1,
          fingerprint: "f",
          sample: "s",
        },
      ],
    },
  });
  expect(root.textContent).toContain("报告解析失败");
});

it("measured suggestion renders rows before/after", () => {
  const root = mount();
  renderReport(root, optimizePayload);
  const text = root.textContent ?? "";
  expect(text).toContain("扫描行数 前:");
  expect(text).toContain("orders=1000");
  expect(text).toContain("扫描行数 后:");
  expect(text).toContain("orders=12");
});

it("optimize evidence lists unsampled tables explicitly", () => {
  const root = mount();
  renderReport(root, {
    ...optimizePayload,
    data: {
      ...optimizePayload.data,
      databases: {},
      evidence_env: {
        note: "n",
        tables: [
          {
            database: "shop",
            table: "logs",
            sampled_rows: null,
            estimated_rows: null,
          },
        ],
      },
    },
  });
  expect(root.textContent).toContain("未采样");
});

it("exit-2 optimize report renders failure reasons, not just AI-unconfigured", () => {
  const root = mount();
  renderReport(root, {
    id: "optfail",
    kind: "optimize",
    version: 1,
    source: "optfail.json",
    data: {
      exit_code: 2,
      env_errors: ["shadow container failed: image not found"],
      input_errors: [],
      databases: {},
      evidence_env: { note: "", tables: [] },
      advisor: { configured: false },
    },
  });
  const text = root.textContent ?? "";
  expect(text).toContain("环境错误");
  expect(text).toContain("shadow container failed");
  expect(text).not.toContain("AI 未配置");
});

it("slowlog view renders skipped count", () => {
  const root = mount();
  renderReport(root, {
    id: "slow2",
    kind: "patrol_slowlog",
    version: 1,
    source: "slow2.json",
    data: { entries_parsed: 3, skipped_lines: 2, top: [] },
  });
  expect(root.textContent).toContain("跳过 2 条");
});

it("verify fixture still renders its own conclusions", () => {
  const root = mount();
  renderReport(root, verifyPayload);
  expect(root.textContent).toContain("变更验收");
});
