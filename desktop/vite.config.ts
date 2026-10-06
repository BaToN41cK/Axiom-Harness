import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // No dev server is used: Tauri loads the bundled `dist/` assets (production)
  // and serves them with its own built-in dev server during development.
  clearScreen: false,
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
