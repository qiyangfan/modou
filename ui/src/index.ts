// 从本机 /api/reports 加载报告，并提供侧栏切换。
import "./styles.css";
import { renderReport } from "./views";
import { el } from "./views";
import type { ReportKind, ReportPayload } from "./types";
import { KIND_LABELS } from "./types";

interface ReportSummary {
  id: string;
  kind: ReportKind;
  version: number;
  source: string;
}

async function main(): Promise<void> {
  const app = document.getElementById("app");
  if (!app) return;
  const sidebar = document.createElement("aside");
  const main = document.createElement("main");
  app.appendChild(sidebar);
  app.appendChild(main);
  sidebar.appendChild(document.createElement("h1")).textContent = "墨斗报告";

  let reports: ReportSummary[] = [];
  try {
    const response = await fetch("/api/reports");
    const body = (await response.json()) as { reports?: ReportSummary[] };
    // 契约形如 {reports: [...]}：非数组形态按空处理，不让形状错位炸掉整个入口
    reports = Array.isArray(body.reports) ? body.reports : [];
  } catch {
    main.appendChild(document.createElement("p")).textContent = "无法加载报告数据（本机端点不可达）。";
    return;
  }
  if (reports.length === 0) {
    main.appendChild(document.createElement("p")).textContent = "未加载任何报告。";
    return;
  }

  const payloads = new Map<string, ReportPayload>();
  const render = async (summary: ReportSummary): Promise<void> => {
    let payload = payloads.get(summary.id);
    if (!payload) {
      const response = await fetch(`/api/reports/${encodeURIComponent(summary.id)}`);
      if (!response.ok) {
        throw new Error(`report request failed: ${response.status}`);
      }
      payload = (await response.json()) as ReportPayload;
      payloads.set(summary.id, payload);
    }
    renderReport(main, payload);
  };

  for (const summary of reports) {
    const item = document.createElement("div");
    item.className = "report-item";
    item.appendChild(document.createElement("div")).className = "kind";
    item.lastChild!.textContent = `${KIND_LABELS[summary.kind] ?? summary.kind}`;
    item.appendChild(document.createElement("div")).className = "sub";
    item.lastChild!.textContent = summary.source;
    item.addEventListener("click", () => {
      sidebar.querySelectorAll(".report-item").forEach((n) => n.classList.remove("active"));
      item.classList.add("active");
      render(summary).catch(() => {
        main.replaceChildren(el("div", "card", "报告加载失败：详情见服务端日志。"));
      });
    });
    sidebar.appendChild(item);
  }
  // 默认渲染第一份
  const first = sidebar.querySelector<HTMLElement>(".report-item");
  if (first) first.click();
}

void main();
