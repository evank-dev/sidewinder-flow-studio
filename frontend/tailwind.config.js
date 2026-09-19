/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas:  { bg: '#090c14', grid: '#11172a', border: '#1e2540' },
        surface: { DEFAULT: '#111827', raised: '#1a2235', overlay: '#212d45' },
        accent:  { DEFAULT: '#38bdf8', dim: '#0ea5e9', glow: '#38bdf822' },
        node: {
          trigger:         '#0d2a3a',
          triggerBorder:   '#0ea5e9',
          processor:       '#0d1f1a',
          processorBorder: '#34d399',
          stop:            '#2a1a0d',
          stopBorder:      '#fb923c',
          tableOut:        '#1a1a2e',
          tableOutBorder:  '#818cf8',
          chartOut:        '#1f0d2a',
          chartOutBorder:  '#e879f9',
        },
        status: {
          ok:      '#34d399',
          error:   '#f87171',
          running: '#fbbf24',
          stopped: '#fb923c',
        },
        muted:  '#64748b',
        subtle: '#2d3a52',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-row': 'pulseRow 0.6s ease-out',
        'flow-dot':  'flowDot 1.2s linear infinite',
      },
      keyframes: {
        pulseRow: {
          '0%':   { backgroundColor: 'rgba(56,189,248,0.3)' },
          '100%': { backgroundColor: 'transparent' },
        },
        flowDot: {
          '0%':   { strokeDashoffset: '100' },
          '100%': { strokeDashoffset: '0' },
        },
      },
    },
  },
  plugins: [],
}
