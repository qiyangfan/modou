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
  },
});
