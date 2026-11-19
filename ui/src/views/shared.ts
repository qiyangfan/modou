// 渲染共用的小构件与标签表。
export function el(
  tag: string,
  className?: string,
  text?: string,
): HTMLElement {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function card(...children: HTMLElement[]): HTMLElement {
  const box = el("div", "card");
  children.forEach((c) => box.appendChild(c));
  return box;
}

function detailTable(
  details: { path: string; expected: string; actual: string }[],
): HTMLElement {
  const table = el("table");
  const head = el("tr");
  ["对象/路径", "期望", "实际"].forEach((t) =>
    head.appendChild(el("th", undefined, t)),
  );
  table.appendChild(head);
  for (const d of details) {
    const row = el("tr");
    row.appendChild(el("td", undefined, d.path));
    row.appendChild(el("td", undefined, d.expected));
    row.appendChild(el("td", undefined, d.actual));
    table.appendChild(row);
  }
  return table;
}

interface DetailCardSubject {
  object_type: string;
  object_name: string;
  dimensions?: string[];
  details?: { path: string; expected: string; actual: string }[];
}

export function detailCard(
  badge: HTMLElement,
  subject: DetailCardSubject,
): HTMLElement {
  return card(
    badge,
    el("strong", undefined, `${subject.object_type} ${subject.object_name}`),
    el("div", "muted", `维度：${(subject.dimensions ?? []).join("、")}`),
    detailTable(subject.details ?? []),
  );
}

export function rowsLine(
  label: string,
  accesses: { table: string; rows: number }[] | undefined,
): string {
  const items = (accesses ?? []).map((a) => `${a.table}=${a.rows}`);
  return items.length > 0 ? `${label} ${items.join(" · ")}` : `${label} —`;
}

export const CATEGORY_LABELS: Record<string, string> = {
  added: "新增",
  removed: "缺失",
  changed: "定义变更",
};

export const STATUS_LABELS: Record<string, string> = {
  confirmed_unused: "确认未用",
  low_use: "疑似低用",
  insufficient_data: "数据不足",
  excluded_unique: "排除（唯一性）",
  excluded_fk: "排除（外键）",
};

export const CASE_LABELS: Record<string, string> = {
  duplicate: "列集合完全相同",
  prefix_non_unique: "非唯一前缀覆盖",
  unique_prefix: "唯一前缀使更长索引冗余",
};
