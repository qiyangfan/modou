export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      [
        "feat",
        "fix",
        "docs",
        "chore",
        "ci",
        "refactor",
        "perf",
        "test",
        "build",
        "release",
        "init",
        "revert",
      ],
    ],
    "header-max-length": [2, "always", 120],
    // 中文正文无自然折行，关闭按字符数硬切的规则。
    "body-max-line-length": [0, "always"],
  },
};
