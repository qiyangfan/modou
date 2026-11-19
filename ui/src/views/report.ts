// 按报告类型分发渲染；结构不完整时显示错误卡而非白屏。
import { KIND_LABELS, type ReportPayload } from "../types";
import { renderLint } from "./lint";
import { renderAiOpinions } from "./opinions";
import { renderOptimize } from "./optimize";
import {
  renderPatrolDrift,
  renderPatrolSlowlog,
  renderPatrolUnused,
} from "./patrol";
import { card, el } from "./shared";
import { renderPatrolSummary } from "./summary";
import { renderVerify } from "./verify";

export function renderReport(root: HTMLElement, payload: ReportPayload): void {
  root.replaceChildren();
  root.appendChild(
    el(
      "h2",
      undefined,
      `${KIND_LABELS[payload.kind] ?? payload.kind}（${payload.source}）`,
    ),
  );
  try {
    renderByKind(root, payload);
    renderAiOpinions(root, payload.data);
  } catch {
    // kind/version 门禁放行但缺契约字段的报告（手写/截断/旧版）：错误卡而非白屏
    root.appendChild(
      card(
        el("span", "badge error", "报告解析失败"),
        el("span", "muted", "报告结构不完整或与契约不符，无法渲染。"),
      ),
    );
  }
}

function renderByKind(root: HTMLElement, payload: ReportPayload): void {
  switch (payload.kind) {
    case "verify":
      renderVerify(root, payload);
      break;
    case "optimize":
      renderOptimize(root, payload);
      break;
    case "lint":
      renderLint(root, payload);
      break;
    case "patrol_drift":
      renderPatrolDrift(root, payload);
      break;
    case "patrol_unused_indexes":
      renderPatrolUnused(root, payload);
      break;
    case "patrol_slowlog":
      renderPatrolSlowlog(root, payload);
      break;
    case "patrol_summary":
      renderPatrolSummary(root, payload);
      break;
    default: {
      const unknown: never = payload.kind;
      root.appendChild(
        card(el("span", "badge error", `未知报告类型：${String(unknown)}`)),
      );
    }
  }
}
