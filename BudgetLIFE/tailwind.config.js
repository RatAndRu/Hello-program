/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Тёмная «стеклянная» палитра
        ink: {
          950: '#070b16',
          900: '#0b1020',
          850: '#0e1425',
          800: '#131a2e',
          750: '#182137',
          700: '#1d2540',
          600: '#27314f',
          500: '#3a466b',
        },
        brand: {
          50: '#eefbff',
          100: '#d7f6ff',
          200: '#b0ecff',
          300: '#78dcff',
          400: '#38c3f5',
          500: '#0ea5e9',
          600: '#0083bf',
          700: '#046a99',
          800: '#0a587f',
          900: '#0f4969',
        },
        mint: {
          400: '#34e5b0',
          500: '#10d19a',
          600: '#05b083',
        },
        rose: {
          400: '#fb7d8e',
          500: '#f43f5e',
          600: '#e11d48',
        },
        amberx: {
          400: '#fbbf5c',
          500: '#f59e0b',
        },
        viola: {
          400: '#a78bfa',
          500: '#8b5cf6',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Manrope', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        glass: '0 1px 0 0 rgba(255,255,255,0.05) inset, 0 20px 50px -20px rgba(0,0,0,0.7)',
        glow: '0 0 0 1px rgba(56,195,245,0.25), 0 10px 40px -12px rgba(56,195,245,0.35)',
        card: '0 12px 32px -18px rgba(0,0,0,0.9)',
      },
      backgroundImage: {
        'grid-fade':
          'linear-gradient(to bottom, rgba(255,255,255,0.045) 1px, transparent 1px), linear-gradient(to right, rgba(255,255,255,0.045) 1px, transparent 1px)',
        'aurora':
          'radial-gradient(60% 60% at 15% 10%, rgba(56,195,245,0.18) 0%, transparent 60%), radial-gradient(50% 50% at 85% 0%, rgba(139,92,246,0.18) 0%, transparent 60%), radial-gradient(60% 60% at 60% 100%, rgba(16,209,154,0.12) 0%, transparent 60%)',
      },
      keyframes: {
        'fade-in': { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        'slide-up': {
          '0%': { opacity: '0', transform: 'translateY(10px) scale(0.99)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        'pop-in': {
          '0%': { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
        'pulse-soft': { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.55' } },
      },
      animation: {
        'fade-in': 'fade-in .25s ease-out both',
        'slide-up': 'slide-up .28s cubic-bezier(.22,1,.36,1) both',
        'pop-in': 'pop-in .18s ease-out both',
        shimmer: 'shimmer 2.2s linear infinite',
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
