// ── 规则审核 ────────────────────────────────────────────────────────────────
import type { LintHit, ReportPayload } from "../types";
import { card, el } from "./shared";

export function renderLint(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as { summary: { hits: number }; hits: LintHit[] };
  root.appendChild(
    card(el("span", "summary-row", `命中 ${data.summary?.hits ?? 0} 条`)),
  );
  const table = el("table");
  const head = el("tr");
  ["级别", "规则", "位置", "消息", "建议"].forEach((t) =>
    head.appendChild(el("th", undefined, t)),
  );
  table.appendChild(head);
  for (const hit of data.hits ?? []) {
    table.appendChild(lintRow(hit));
  }
  root.appendChild(card(table));
}

function lintRow(hit: LintHit): HTMLElement {
  const row = el("tr");
  const level = el("td");
  level.appendChild(el("span", `badge ${hit.level}`, hit.level));
  row.appendChild(level);
  row.appendChild(el("td", undefined, hit.rule_id));
  row.appendChild(el("td", undefined, `${hit.file}:${hit.line}`));
  row.appendChild(el("td", undefined, hit.message));
  row.appendChild(el("td", undefined, hit.suggestion));
  return row;
}
