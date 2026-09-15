import react from "@vitejs/plugin-react";
// `defineConfig` de "vitest/config" (nao "vite") -- e o mesmo defineConfig
// do Vite, so com o campo `test` (abaixo) tipado tambem, sem precisar de
// referencia de tipos separada.
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
  server: {
    // Em desenvolvimento (npm run dev), o backend Python real continua
    // rodando em 127.0.0.1:8765 (python webui.py) -- este proxy evita ter
    // que lidar com CORS e mantem o mesmo caminho relativo "/api/..." que
    // o build de producao usa quando o proprio Python serve o build.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
