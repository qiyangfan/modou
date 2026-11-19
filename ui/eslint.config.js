import tseslint from "typescript-eslint";

export default tseslint.config(
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
      // 结构与复杂度门禁，采用 ESLint 默认阈值：复杂度 20 / 嵌套 4 / 文件 300 行 /
      // 函数 50 行 / 参数 3。
      complexity: "error",
      "max-depth": "error",
      "max-lines": "error",
      "max-lines-per-function": "error",
      "max-params": "error",
    },
  },
  {
    ignores: ["dist/**", "node_modules/**"],
  },
);
