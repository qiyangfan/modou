// ── 综合巡检 ────────────────────────────────────────────────────────────────
import type { PatrolSummarySignals, ReportPayload } from "../types";
import { CATEGORY_LABELS, STATUS_LABELS, card, el } from "./shared";

type DriftSignal = NonNullable<PatrolSummarySignals["drift"]>;
type UnusedSignal = NonNullable<PatrolSummarySignals["unused"]>;
type SlowlogSignal = NonNullable<PatrolSummarySignals["slowlog"]>;

export function renderPatrolSummary(
  root: HTMLElement,
  payload: ReportPayload,
): void {
  const data = payload.data as {
    exit_code: number;
    generated_at?: string;
    inputs?: Record<string, string | null>;
    signals: PatrolSummarySignals;
  };
  root.appendChild(
    card(el("span", "badge kind", `退出码 ${data.exit_code ?? "-"}`)),
  );
  renderInputs(root, data.inputs);
  const signals = data.signals ?? {};
  if (signals.drift) renderDriftSignal(root, signals.drift);
  if (signals.unused) renderUnusedSignal(root, signals.unused);
  if (signals.slowlog) renderSlowlogSignal(root, signals.slowlog);
  root.appendChild(
    card(
      el(
        "div",
        "muted",
        "明细为摘要截断（对象 ≤20 · 指纹前 3），完整结论见各信号报告。",
      ),
    ),
  );
}

function renderInputs(
  root: HTMLElement,
  inputs: Record<string, string | null> | undefined,
): void {
  const sources = Object.entries(inputs ?? {})
    .map(([signal, source]) => `${signal}=${source ?? "—"}`)
    .join(" · ");
  if (sources) {
    root.appendChild(card(el("span", "muted", `输入来源 ${sources}`)));
  }
}

function renderDriftSignal(root: HTMLElement, signal: DriftSignal): void {
  root.appendChild(
    card(
      el(
        "span",
        "summary-row",
        `漂移：新增 ${signal.added} · 缺失 ${signal.removed} · 定义变更 ${signal.changed}`,
      ),
    ),
  );
  for (const object of signal.objects ?? []) {
    root.appendChild(
      card(
        el(
          "span",
          `badge ${object.category}`,
          CATEGORY_LABELS[object.category] ?? object.category,
        ),
        el(
          "code",
          undefined,
          `${object.database}.${object.object_type}:${object.object_name}`,
        ),
      ),
    );
  }
}

function renderUnusedSignal(root: HTMLElement, signal: UnusedSignal): void {
  root.appendChild(
    card(
      el(
        "span",
        "summary-row",
        `未用索引：确认未用 ${signal.confirmed_unused} · 疑似低用 ${signal.low_use} · ` +
          `数据不足 ${signal.insufficient_data} · 冗余 ${signal.redundant}`,
      ),
    ),
  );
  for (const item of signal.items ?? []) {
    root.appendChild(
      card(
        el("code", undefined, `${item.database}.${item.table}.${item.index}`),
        el("span", "muted", STATUS_LABELS[item.status] ?? item.status),
      ),
    );
  }
}

function renderSlowlogSignal(root: HTMLElement, signal: SlowlogSignal): void {
  root.appendChild(
    card(
      el(
        "span",
        "summary-row",
        `慢日志：解析条目 ${signal.entries_parsed} · 指纹榜 ${signal.fingerprints}`,
      ),
    ),
  );
  for (const top of signal.top ?? []) {
    root.appendChild(
      card(
        el(
          "strong",
          undefined,
          `次数 ${top.count} · 累计 ${top.query_time_total.toFixed(3)}s · 扫描 ${top.rows_examined_total} 行`,
        ),
        el("div", "muted", top.fingerprint),
      ),
    );
  }
}
