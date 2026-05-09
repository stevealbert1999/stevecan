import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  build: {
    target: "es2022",
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        memory: resolve(__dirname, "memory.html"),
        butler: resolve(__dirname, "butler.html"),
        lab: resolve(__dirname, "lab.html"),
      },
    },
  },
});
