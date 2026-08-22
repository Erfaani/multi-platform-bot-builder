import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Self-hosted in production; no external CDN (SECURITY.md, I18N.md §3).
        sans: ["var(--font-latin)", "Manrope", "system-ui", "sans-serif"],
        persian: ["var(--font-persian)", "Estedad", "Vazirmatn", "Tahoma", "sans-serif"],
      },
      colors: {
        background: "rgb(var(--background) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-raised": "rgb(var(--surface-raised) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        "muted-light": "rgb(var(--muted-light) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        "accent-strong": "rgb(var(--accent-strong) / <alpha-value>)",
        "accent-soft": "rgb(var(--accent-soft) / <alpha-value>)",
        secondary: "rgb(var(--secondary) / <alpha-value>)",
        "secondary-strong": "rgb(var(--secondary-strong) / <alpha-value>)",
        "secondary-soft": "rgb(var(--secondary-soft) / <alpha-value>)",
        premium: "rgb(var(--premium) / <alpha-value>)",
        "premium-soft": "rgb(var(--premium-soft) / <alpha-value>)",
        dark: "rgb(var(--dark) / <alpha-value>)",
        "dark-raised": "rgb(var(--dark-raised) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};

export default config;
