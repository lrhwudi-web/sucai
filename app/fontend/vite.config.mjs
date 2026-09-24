import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendProxy = {
  "/api": "http://127.0.0.1:8001",
  "/thumb": "http://127.0.0.1:8001",
  "/media": "http://127.0.0.1:8001",
  "/download": "http://127.0.0.1:8001",
  "/sku": "http://127.0.0.1:8001",
  "/admin": "http://127.0.0.1:8001",
  "/auth": "http://127.0.0.1:8001",
  "/login": "http://127.0.0.1:8001",
  "/logout": "http://127.0.0.1:8001",
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 4173,
    strictPort: true,
    allowedHosts: ["terminal.local"],
    proxy: backendProxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
    strictPort: true,
    proxy: backendProxy,
  }
});
