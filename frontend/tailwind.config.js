/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Acme Finance palette
        gold: "#C3A35B",
        goldLight: "#E8D5A3",
        ink: "#0F0F0F",
        inkSoft: "#171717",
        line: "#2A2620",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
