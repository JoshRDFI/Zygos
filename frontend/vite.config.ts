/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Override when :8000 is taken, e.g. ZYGOS_BACKEND=http://127.0.0.1:8010 npm run preview
const BACKEND = process.env.ZYGOS_BACKEND ?? "http://127.0.0.1:8000";

const proxy = {
  "/sessions": { target: BACKEND, changeOrigin: true },
  "/runtime": { target: BACKEND, changeOrigin: true },
  "/ws": { target: BACKEND, changeOrigin: true, ws: true },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  // `vite preview` serves the production build, where /public (the vendored VAD
  // wasm) is served as-is — unlike the dev server, which refuses to serve a
  // /public file through its module-transform pipeline. Same backend proxy.
  preview: { port: 5173, proxy },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
  },
});
