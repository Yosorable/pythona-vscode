import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  build: { target: 'safari17', sourcemap: false, chunkSizeWarningLimit: 12000 },
  worker: { format: 'es' },
  resolve: { dedupe: ['vscode', 'monaco-editor', '@codingame/monaco-vscode-api'] },
  server: {
    host: '127.0.0.1',
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
  },
});
