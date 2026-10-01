import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api/* → FastAPI(uvicorn app.server:app --port 8000). CORS 설정 없이 개발 서버가 대신 전달한다.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
