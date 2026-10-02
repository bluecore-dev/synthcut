import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:3400" },
  },
  build: {
    target: "es2020",
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
});
