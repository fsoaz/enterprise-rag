import type { Config } from "tailwindcss";

export default {
  // `dark:` variants follow the OS preference, matching the prefers-color-scheme
  // block in globals.css. Without this the palette flipped the page background to
  // near-black while every utility class stayed on the light palette.
  darkMode: "media",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
