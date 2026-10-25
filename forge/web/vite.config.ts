import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API of a running `bin/forge-server` (loopback only).
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": "http://127.0.0.1:8920" } },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
});
