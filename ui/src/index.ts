// 从本机 /api/reports 加载报告，并提供侧栏切换。
import "./styles.css";
import { el, renderReport } from "./views";
import type { ReportKind, ReportPayload } from "./types";
import { KIND_LABELS } from "./types";

interface ReportSummary {
  id: string;
  kind: ReportKind;
  version: number;
  source: string;
}

async function main(): Promise<void> {
  const shell = mountShell();
  if (!shell) return;
  const body = await fetchReportList();
  if (!body) {
    shell.main.appendChild(document.createElement("p")).textContent =
      "无法加载报告数据（本机端点不可达）。";
    return;
  }
  // 契约形如 {reports: [...]}：非数组形态按空处理，不让形状错位炸掉整个入口
  const reports = Array.isArray(body.reports) ? body.reports : [];
  if (reports.length === 0) {
    shell.main.appendChild(document.createElement("p")).textContent =
      "未加载任何报告。";
    return;
  }
  setupReportNavigation(shell.sidebar, shell.main, reports);
}

function mountShell(): { sidebar: HTMLElement; main: HTMLElement } | undefined {
  const app = document.getElementById("app");
  if (!app) return undefined;
  const sidebar = document.createElement("aside");
  const main = document.createElement("main");
  app.appendChild(sidebar);
  app.appendChild(main);
  sidebar.appendChild(document.createElement("h1")).textContent = "墨斗报告";
  return { sidebar, main };
}

async function fetchReportList(): Promise<
  { reports?: ReportSummary[] } | undefined
> {
  try {
    const response = await fetch("/api/reports");
    return (await response.json()) as { reports?: ReportSummary[] };
  } catch {
    return undefined;
  }
}

function setupReportNavigation(
  sidebar: HTMLElement,
  main: HTMLElement,
  reports: ReportSummary[],
): void {
  const payloads = new Map<string, ReportPayload>();
  const render = async (summary: ReportSummary): Promise<void> => {
    let payload = payloads.get(summary.id);
    if (!payload) {
      const response = await fetch(
        `/api/reports/${encodeURIComponent(summary.id)}`,
      );
      if (!response.ok) {
        throw new Error(`report request failed: ${response.status}`);
      }
      payload = (await response.json()) as ReportPayload;
      payloads.set(summary.id, payload);
    }
    renderReport(main, payload);
  };
  const context = { sidebar, main, render };
  for (const summary of reports) {
    sidebar.appendChild(buildReportItem(summary, context));
  }
  // 默认渲染第一份
  const first = sidebar.querySelector<HTMLElement>(".report-item");
  if (first) first.click();
}

interface NavContext {
  sidebar: HTMLElement;
  main: HTMLElement;
  render: (summary: ReportSummary) => Promise<void>;
}

function buildReportItem(
  summary: ReportSummary,
  context: NavContext,
): HTMLElement {
  const item = document.createElement("div");
  item.className = "report-item";
  const kind = item.appendChild(document.createElement("div"));
  kind.className = "kind";
  kind.textContent = `${KIND_LABELS[summary.kind] ?? summary.kind}`;
  const sub = item.appendChild(document.createElement("div"));
  sub.className = "sub";
  sub.textContent = summary.source;
  item.addEventListener("click", () => {
    context.sidebar
      .querySelectorAll(".report-item")
      .forEach((n) => n.classList.remove("active"));
    item.classList.add("active");
    context.render(summary).catch(() => {
      context.main.replaceChildren(
        el("div", "card", "报告加载失败：详情见服务端日志。"),
      );
    });
  });
  return item;
}

void main();
