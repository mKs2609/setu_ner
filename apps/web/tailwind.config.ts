import type { Config } from "tailwindcss";

// Visual design intentionally deferred -- see project agreement: core loop
// first, UI/UX pass once accessibility/logistics/scenario flows work.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
