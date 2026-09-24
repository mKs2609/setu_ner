import type { Config } from "tailwindcss";

/**
 * The design system, in Tailwind's vocabulary. Tokens mirror app/globals.css,
 * which stays the source of truth.
 *
 * A near-monochrome light system with one violet running through it: an
 * almost-white canvas, crisp white cards, near-black doing the structural
 * work, and violet reserved for the thing that needs attention. Headlines are
 * whisper-thin (weight 200) against body and interface text at 500; the
 * contrast between them is the typographic idea.
 *
 * Risk colours are the exception to "one accent". A flood map needs to say
 * safe, caution and cut-off at a glance, and violet cannot carry three
 * meanings at once -- so those three are functional, never decorative.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#fbfaff",        // page background, barely tinted
        surface: "#ffffff",       // cards sitting on the canvas
        ink: "#100f12",           // text, borders, filled buttons
        muted: "#6f6b7a",         // secondary text
        line: "#e7e3f0",          // hairline borders, lavender-tinted
        accent: {
          DEFAULT: "#8d6fde",     // the violet pulse
          deep: "#6f4fc9",        // hover / pressed
          wash: "#ebe5ff",        // tinted fills
          mist: "#d9cffa",        // second wash, charts
        },
        ok: "#2f7d5d",            // road usable
        caution: "#b06a15",       // degraded
        alert: "#c03a3a",         // cut off
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        micro: ["11px", { lineHeight: "1.3", letterSpacing: "0.04em" }],
        caption: ["13px", { lineHeight: "1.45" }],
        ui: ["15px", { lineHeight: "1.5" }],
        body: ["17px", { lineHeight: "1.6" }],
        subheading: ["22px", { lineHeight: "1.35" }],
        readout: ["40px", { lineHeight: "1.05", letterSpacing: "-0.02em" }],
        heading: ["clamp(2.2rem, 5vw, 3.4rem)", { lineHeight: "1.08", letterSpacing: "-0.02em" }],
        display: ["clamp(2.8rem, 7vw, 5rem)", { lineHeight: "1.02", letterSpacing: "-0.03em" }],
      },
      borderRadius: {
        DEFAULT: "12px",
        card: "17px",
        pill: "9999px",
      },
      maxWidth: {
        page: "1150px",
      },
      spacing: {
        section: "72px",
      },
      boxShadow: {
        // Barely there: cards lift off the tinted canvas without drama.
        card: "0 1px 2px rgba(16, 15, 18, 0.04), 0 8px 24px -16px rgba(16, 15, 18, 0.18)",
      },
    },
  },
  plugins: [],
};

export default config;
