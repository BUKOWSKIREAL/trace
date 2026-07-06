const { defineConfig } = require('vite');
const vue = require('@vitejs/plugin-vue');
const path = require('path');

module.exports = defineConfig({
  plugins: [vue()],
  base: './',
  root: __dirname,
  build: {
    outDir: path.join(__dirname, 'renderer-dist'),
    emptyOutDir: true,
  },
});
