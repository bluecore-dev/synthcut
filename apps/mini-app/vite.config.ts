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
    // Fonts stay separate files: the CSP allows font-src 'self' only, so an
    // inlined data: font would be blocked.
    assetsInlineLimit: (file: string) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
});
