import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The live site once told its visitors "is the backend running on port 8000?"
 * whenever the API was slow to wake. There is no port 8000 in production, and
 * nobody outside this repository can act on that advice.
 *
 * The hint is chosen from the API base the build was given, so these tests
 * import the module fresh with the environment set each way.
 */

afterEach(() => {
  vi.resetModules();
  delete process.env.NEXT_PUBLIC_API_URL;
});

async function hintFor(base: string | undefined, error: unknown) {
  vi.resetModules();
  if (base === undefined) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = base;
  const { apiErrorHint } = await import("@/lib/api");
  return apiErrorHint(error);
}

describe("apiErrorHint", () => {
  it("tells a developer to start the backend", async () => {
    const hint = await hintFor("http://localhost:8000", new Error("Failed to fetch"));
    expect(hint).toContain("Failed to fetch");
    expect(hint).toContain("is the API running on");
    expect(hint).toContain("localhost:8000");
  });

  it("defaults to the developer hint when no API URL is configured", async () => {
    const hint = await hintFor(undefined, new Error("Failed to fetch"));
    expect(hint).toContain("is the API running on");
  });

  it("never mentions a port to someone on the deployed site", async () => {
    const hint = await hintFor("https://setuner-api.onrender.com", new Error("Failed to fetch"));
    expect(hint).not.toContain("port 8000");
    expect(hint).not.toContain("localhost");
    expect(hint).not.toContain("is the API running on");
  });

  it("explains the cold start instead, which is the real cause", async () => {
    const hint = await hintFor("https://setuner-api.onrender.com", new Error("Failed to fetch"));
    expect(hint).toContain("Failed to fetch");
    expect(hint).toContain("sleeps when idle");
    expect(hint).toContain("Try again in a moment.");
  });

  it("carries the underlying message either way, rather than swallowing it", async () => {
    const local = await hintFor("http://127.0.0.1:8000", new Error("NetworkError"));
    const live = await hintFor("https://setuner-api.onrender.com", new Error("NetworkError"));
    expect(local).toContain("NetworkError");
    expect(live).toContain("NetworkError");
  });

  it("handles a thrown value that is not an Error", async () => {
    const hint = await hintFor("https://setuner-api.onrender.com", "boom");
    expect(hint).toContain("boom");
  });
});
