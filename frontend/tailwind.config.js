/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Core Marathon palette
        'm-black': '#000000',
        'm-bg': '#050508',
        'm-surface': '#0a0a10',
        'm-card': '#0f0f18',
        'm-border': '#1a1a2a',
        'm-border-bright': '#2a2a40',

        // Accent — Marathon neon lime
        'm-green': '#c8ff00',
        'm-green-dim': '#a0cc00',
        'm-green-glow': 'rgba(200, 255, 0, 0.08)',
        'm-green-bright': '#d4ff2a',

        // Status
        'm-red': '#ff2244',
        'm-red-dim': '#cc1133',
        'm-red-glow': 'rgba(255, 34, 68, 0.08)',
        'm-yellow': '#ffcc00',
        'm-cyan': '#00ddff',
        'm-purple': '#8844ff',

        // Text
        'm-text': '#e8e8f0',
        'm-text-dim': '#888899',
        'm-text-muted': '#555566',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', '"Consolas"', 'monospace'],
        display: ['"Inter"', '"Helvetica Neue"', 'Arial', 'sans-serif'],
      },
      fontSize: {
        '2xs': '0.625rem',
      },
      borderWidth: {
        '1': '1px',
      },
      animation: {
        'pulse-slow': 'pulse 3s ease-in-out infinite',
        'scan': 'scan 4s linear infinite',
      },
      keyframes: {
        scan: {
          '0%': { backgroundPosition: '0% 0%' },
          '100%': { backgroundPosition: '0% 100%' },
        },
      },
    },
  },
  plugins: [],
}
