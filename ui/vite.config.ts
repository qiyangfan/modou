import { defineConfig } from "vite";

export default defineConfig({
  // 零外链红线：构建产物必须完全自包含（无 CDN、无字体/脚本外链）
  build: {
    outDir: "dist",
    assetsInlineLimit: 1024 * 1024,
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
    // 阈值按实测基线取整：2026-11-19 为 lines 93.53 / statements 92.41 /
    // functions 96.22 / branches 66.00。
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      thresholds: {
        lines: 90,
        statements: 90,
        functions: 90,
        branches: 60,
      },
    },
  },
});
