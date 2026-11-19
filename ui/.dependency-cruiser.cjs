module.exports = {
  forbidden: [
    {
      name: "no-circular",
      severity: "error",
      from: {},
      to: { circular: true },
    },
    {
      name: "no-unresolvable",
      severity: "error",
      from: {},
      to: { couldNotResolve: true },
    },
    {
      name: "no-orphans",
      severity: "error",
      from: { orphan: true, pathNot: ["^src/index\\.ts$", "\\.d\\.ts$"] },
      to: {},
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    tsConfig: { fileName: "tsconfig.json" },
    exclude: { path: ["^dist/", "^node_modules/"] },
  },
};
