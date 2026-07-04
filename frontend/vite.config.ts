import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Emit the production build *inside* the Python package so that it ships as
  // package data in the wheel and is found at runtime regardless of where
  // Boulder is installed (see boulder/api/main.py).
  build: {
    outDir: path.resolve(__dirname, "../boulder/_frontend"),
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8050",
        changeOrigin: true,
      },
    },
  },
});
