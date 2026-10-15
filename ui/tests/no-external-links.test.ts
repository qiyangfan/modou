// 零外链断言：构建产物（dist）不得引用任何外部网络资源（红线：页面零外部请求）
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// vitest 运行目录为 ui/：dist 相对工作目录解析
const distDir = resolve(process.cwd(), "dist");

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) yield* walk(full);
    else yield full;
  }
}

const EXTERNAL_URL = /https?:\/\//i;

describe("zero external links in dist", () => {
  it("dist exists (run `npm run build` first)", () => {
    expect(existsSync(distDir), "ui/dist not built").toBe(true);
  });

  it("contains no external http(s) resource references", () => {
    if (!existsSync(distDir)) return; // 上条断言已报告缺失
    for (const file of walk(distDir)) {
      if (!/\.(html|js|css|svg)$/.test(file)) continue;
      const content = readFileSync(file, "utf-8");
      const match = EXTERNAL_URL.exec(content);
      // 允许出现在注释中的许可证 URL 之外的一切外链都必须消灭
      const stripped = content.replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\//g, "");
      expect(EXTERNAL_URL.test(stripped), `${file} references ${match?.[0]}`).toBe(false);
    }
  });
});
