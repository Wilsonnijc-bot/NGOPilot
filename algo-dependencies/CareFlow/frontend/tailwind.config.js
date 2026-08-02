/** CareFlow Tailwind 設定 — 編輯室 / 檔案夾 風格 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        serif: ['"Noto Serif TC"', '"Songti TC"', '"Songti SC"', 'STSong', 'serif'],
        sans: ['"PingFang HK"', '"PingFang TC"', '"Helvetica Neue"', '"Hiragino Sans GB"', '"Microsoft JhengHei"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', '"Menlo"', 'monospace'],
      },
      colors: {
        paper: {
          50: '#fcfaf3', 100: '#f8f3e8', 200: '#efe7d3', 300: '#dccfb0',
          400: '#a99b7a', 500: '#7a6e51',
        },
        ink: {
          50: '#f7f5f0', 100: '#e8e3d7', 400: '#5a544a', 500: '#3d3933',
          700: '#1f1c18', 900: '#0e0c0a',
        },
        cinnabar: {
          50: '#fbeae5', 100: '#f5c8bb', 400: '#c75a3f', 500: '#a8412c',
          600: '#8a3120', 700: '#6b2419',
        },
        sage: { 50: '#eef2ec', 100: '#d6e0d1', 500: '#4a6c5d', 700: '#2e4639' },
        amber_ink: { 50: '#faf2dc', 500: '#a8841f', 700: '#6b5310' },
      },
      letterSpacing: { eyebrow: '0.18em' },
      boxShadow: {
        sheet: '0 1px 0 rgba(20,18,14,0.06), 0 24px 48px -32px rgba(20,18,14,0.18)',
      },
    },
  },
  plugins: [],
};
