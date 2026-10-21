// 入口集成测试：fetch 返回 {reports:[...]} 时正确解析并渲染。
import { beforeEach, describe, expect, it, vi } from "vitest";

function stubFetchBodies(bodies: unknown[]): void {
  const queue = [...bodies];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => queue.shift(),
    })),
  );
}

describe("index entry", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    document.body.innerHTML = '<div id="app"></div>';
    vi.unstubAllGlobals();
    vi.resetModules(); // index.ts 模块级 main() 只在首次求值运行，每个用例重置模块表
  });

  it("renders sidebar items and first report from object-shaped list", async () => {
    stubFetchBodies([
      { reports: [{ id: "/tmp/r.json", kind: "lint", version: 1, source: "r.json" }] },
      {
        id: "/tmp/r.json",
        kind: "lint",
        version: 1,
        source: "r.json",
        data: { summary: { hits: 0 }, hits: [] },
      },
    ]);
    await import("../src/index");
    await new Promise((r) => setTimeout(r, 0));
    const app = document.getElementById("app")!;
    expect(app.querySelectorAll(".report-item").length).toBe(1);
    expect(app.querySelector("main")!.textContent).toContain("命中 0 条");
  });

  it("malformed list shape degrades to empty state, not a crash", async () => {
    stubFetchBodies([{ wrong: [] }]);
    await import("../src/index");
    await new Promise((r) => setTimeout(r, 0));
    const app = document.getElementById("app")!;
    expect(app.querySelector("main")!.textContent).toContain("未加载任何报告");
  });
});
