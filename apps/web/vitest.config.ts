import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

/**
 * Tests for the parts of the interface that can be wrong without anyone
 * noticing: the colour ramp's contrast, the committed flood record, and the
 * two server-rendered charts.
 *
 * Node environment, not jsdom. Both charts are server components with no
 * client JavaScript, so `renderToStaticMarkup` exercises exactly what a
 * reader receives, and there is no DOM to simulate.
 */
export default defineConfig({
  esbuild: {
    // next's tsconfig sets jsx: "preserve" for the compiler; esbuild needs a
    // real transform to run the .tsx files here.
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
