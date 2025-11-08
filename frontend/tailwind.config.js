/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        scian: {
          // Brand accent colors
          cyan: '#4FC3F7',
          peach: '#FF9E80',
          blue: '#42A5F5',
          violet: '#AB47BC',
          green: '#66BB6A',

          // VSCode Dark+ theme backgrounds
          darker: '#1E1E1E',      // Main editor background
          dark: '#252526',         // Sidebar/panel background
          panel: '#2D2D30',        // Panel header
          hover: '#2A2D2E',        // Hover state
          border: '#3E3E42',       // Borders

          // Text colors (VSCode-inspired) - FLATTENED for @apply
          'text-primary': '#CCCCCC',    // Main text
          'text-secondary': '#858585',  // Secondary text
          'text-muted': '#6A6A6A',      // Muted text
        },
        // Platform-specific brand colors
        platform: {
          'instagram-start': '#833AB4',    // Instagram gradient start
          'instagram-mid': '#E1306C',      // Instagram gradient middle
          'instagram-end': '#FD1D1D',      // Instagram gradient end
          'facebook': '#1877F2',            // Facebook blue
          'twitter': '#1DA1F2',             // Twitter blue
          'tiktok': '#000000',              // TikTok black
          'tiktok-accent': '#FF0050',       // TikTok pink/red
          'linkedin': '#0A66C2',            // LinkedIn blue
          'youtube': '#FF0000',             // YouTube red
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
        display: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
        mono: ['Consolas', 'Monaco', 'Courier New', 'monospace'],
      },
    },
  },
  plugins: [],
  darkMode: 'class',
}
