import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Backend URL for the dev proxy. Override with GOLD_AI_BACKEND=http://host:port npm run dev
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backend = env.GOLD_AI_BACKEND || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    base: "/",
    server: {
      port: 5173,
      proxy: {
        "/api": { target: backend, changeOrigin: true },
        "/ws": { target: backend.replace(/^http/, "ws"), ws: true, changeOrigin: true },
      },
    },
    build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
  };
});
