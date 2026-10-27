import { afterEach, describe, expect, it, vi } from "vitest";

import { retryingFetch } from "@/lib/api";

/**
 * The API sleeps on a free instance. A phone opening the site after a quiet
 * spell used to get one refused request and an error telling the reader to
 * try again themselves — while the loading state on the same page promised
 * the wait could take a minute. Asking again is the system's job.
 *
 * The delays are passed in as zeros so these run instantly; the real policy
 * is RETRY_DELAYS_MS.
 */

const NONE = [0, 0, 0];

afterEach(() => {
  vi.unstubAllGlobals();
});

function respond(sequence: Array<number | "network-error">) {
  const calls = { n: 0 };
  vi.stubGlobal("fetch", async () => {
    const next = sequence[Math.min(calls.n, sequence.length - 1)];
    calls.n += 1;
    if (next === "network-error") throw new TypeError("Failed to fetch");
    return new Response("{}", { status: next });
  });
  return calls;
}

describe("retryingFetch", () => {
  it("retries a read that failed to connect, and succeeds", async () => {
    const calls = respond(["network-error", "network-error", 200]);
    const res = await retryingFetch("/x", undefined, NONE);
    expect(res.status).toBe(200);
    expect(calls.n).toBe(3);
  });

  it("retries a read that got a 503 while the host was waking", async () => {
    const calls = respond([503, 200]);
    const res = await retryingFetch("/x", undefined, NONE);
    expect(res.status).toBe(200);
    expect(calls.n).toBe(2);
  });

  it("gives up after the configured attempts and rethrows", async () => {
    const calls = respond(["network-error"]);
    await expect(retryingFetch("/x", undefined, NONE)).rejects.toThrow("Failed to fetch");
    expect(calls.n).toBe(NONE.length + 1);
  });

  it("never retries a write, because a repeated POST files a second record", async () => {
    const calls = respond(["network-error"]);
    await expect(
      retryingFetch("/x", { method: "POST" }, NONE),
    ).rejects.toThrow("Failed to fetch");
    expect(calls.n).toBe(1);
  });

  it("does not retry a 5xx on a write either", async () => {
    const calls = respond([500, 200]);
    const res = await retryingFetch("/x", { method: "POST" }, NONE);
    expect(res.status).toBe(500);
    expect(calls.n).toBe(1);
  });

  it("does not retry a 404, which will not become a 200", async () => {
    const calls = respond([404, 200]);
    const res = await retryingFetch("/x", undefined, NONE);
    expect(res.status).toBe(404);
    expect(calls.n).toBe(1);
  });

  it("returns a first-try success without sleeping on anything", async () => {
    const calls = respond([200]);
    const res = await retryingFetch("/x", undefined, NONE);
    expect(res.status).toBe(200);
    expect(calls.n).toBe(1);
  });
});
