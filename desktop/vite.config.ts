import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Tauri expects a fixed port and the env var guarded entry
  clearScreen: false,
  server: {
    // A literal IP (not "localhost") keeps the URL stable when VPN adapters
    // change how the name resolves between IPv4 and IPv6.
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    target: "es2021",
    minify: "esbuild",
    sourcemap: false,
    rollupOptions: {
      output: {
        // Split heavy, rarely-changing vendors into their own chunks so the
        // main app chunk stays small and the big libraries cache separately.
        // highlight.js in particular is large and only needed for previews.
        manualChunks: {
          "vendor-react": ["react", "react-dom"],
          "vendor-markdown": ["react-markdown", "remark-gfm", "rehype-raw", "rehype-sanitize"],
          "vendor-highlight": ["highlight.js"],
        },
      },
    },
  },
});
