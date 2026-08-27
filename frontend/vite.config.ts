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
        statements: 75,
        branches: 55,
        functions: 75,
        lines: 80,
        perFile: true,
        "src/filters.ts": {
          statements: 90,
          branches: 85,
          functions: 95,
          lines: 95,
        },
        "src/routes.ts": {
          statements: 90,
          branches: 80,
          functions: 95,
          lines: 95,
        },
        "src/use-browser.ts": {
          statements: 82,
          branches: 62,
          functions: 85,
          lines: 85,
        },
        "src/use-resource.ts": {
          statements: 75,
          branches: 55,
          functions: 75,
          lines: 80,
        },
      },
    },
  },
});
