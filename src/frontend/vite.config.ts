import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = process.env.BIDDING_API_TARGET || env.BIDDING_API_TARGET;
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api/v1": {
          target: apiTarget || "http://127.0.0.1:8000",
          changeOrigin: false,
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
      sourcemap: false,
    },
    test: {
      environment: "jsdom",
      include: ["src/**/*.test.{ts,tsx}"],
      setupFiles: ["./src/test-setup.ts"],
      restoreMocks: true,
    },
  };
});
