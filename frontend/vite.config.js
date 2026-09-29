import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Match the origin already permitted by FastAPI's CORS middleware.
  server: { host: 'localhost', port: 5173, strictPort: true },
});
