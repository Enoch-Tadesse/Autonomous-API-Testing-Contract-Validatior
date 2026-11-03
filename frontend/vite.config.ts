import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the Vite server proxies API calls to the FastAPI service on :8000.
// In the demo, FastAPI serves the built files from dist/ itself (one origin, no CORS).
const api = { target: "http://localhost:8000", changeOrigin: true };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/runs": api, "/demo": api, "/health": api } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
});
