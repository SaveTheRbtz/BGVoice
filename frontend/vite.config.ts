import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/connect": "http://127.0.0.1:8000",
      "/v1": "http://127.0.0.1:8000",
    },
  },
  test: {
    coverage: {
      provider: "v8",
      include: [
        "src/routes.ts",
        "src/filters.ts",
        "src/use-browser.ts",
        "src/use-resource.ts",
      ],
      reporter: ["text", "text-summary"],
      thresholds: {
        statements: 90,
        branches: 75,
        functions: 90,
        lines: 95,
        perFile: true,
      },
    },
  },
});
