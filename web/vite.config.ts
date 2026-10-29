import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// BASE : "/ceperadar/" pour GitHub Pages (site de projet). Surchargeable via VITE_BASE.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/ceperadar/",
  plugins: [react()],
  build: { target: "es2020", chunkSizeWarningLimit: 1200 },
});
