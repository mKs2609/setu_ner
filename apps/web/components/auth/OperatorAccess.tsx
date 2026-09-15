"use client";

/**
 * Enter or forget the operator token for this tab.
 *
 * Shown beside every action that needs one. On a local development API with
 * no tokens configured, writes work without it; on a deployment they return
 * 401 until a token is entered here. The token is never displayed back.
 */

import { useEffect, useState } from "react";

import { getOperatorToken, setOperatorToken } from "@/lib/api";

export default function OperatorAccess({ compact = false }: { compact?: boolean }) {
  const [hasToken, setHasToken] = useState(false);
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const sync = () => setHasToken(Boolean(getOperatorToken()));
    sync();
    window.addEventListener("setuner-operator-token", sync);
    return () => window.removeEventListener("setuner-operator-token", sync);
  }, []);

  if (hasToken) {
    return (
      <p className="text-xs text-gray-600">
        Operator token set for this tab.{" "}
        <button onClick={() => setOperatorToken(null)} className="text-teal-700 underline underline-offset-2">
          Forget it
        </button>
      </p>
    );
  }

  if (compact && !open) {
    return (
      <p className="text-xs text-gray-600">
        Deployed sites need an operator token for this.{" "}
        <button onClick={() => setOpen(true)} className="text-teal-700 underline underline-offset-2">
          Enter token
        </button>
      </p>
    );
  }

  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (draft.trim()) {
          setOperatorToken(draft);
          setDraft("");
          setOpen(false);
        }
      }}
    >
      <input
        type="password"
        autoComplete="off"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="Operator token"
        className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1 text-xs"
      />
      <button type="submit" className="rounded bg-gray-800 px-2 py-1 text-xs text-white">
        Use
      </button>
    </form>
  );
}
