"use client";

/**
 * A plan's explanation, section by section. Each statement can be expanded to
 * show the figures it was built from, so a doubtful reader checks the numbers
 * rather than trusting the sentence.
 */

import type { PlanExplanation } from "@/lib/api";

export default function PlanWhy({ explanation }: { explanation: PlanExplanation }) {
  return (
    <div className="space-y-3">
      {explanation.sections
        .filter((s) => s.statements.length > 0)
        .map((section) => (
          <div key={section.title}>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">{section.title}</h4>
            <ul className="mt-1 space-y-1">
              {section.statements.map((st, i) => (
                <li key={i} className="text-xs text-ink">
                  <details>
                    <summary className="cursor-pointer list-none">
                      {st.text}{" "}
                      <span className="text-[10px] text-accent underline underline-offset-2">evidence</span>
                    </summary>
                    <pre className="mt-1 overflow-x-auto rounded bg-surface p-2 text-[10px] text-muted">
                      {JSON.stringify(st.evidence, null, 1)}
                    </pre>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))}
      <p className="text-[11px] text-muted">{explanation.method}</p>
    </div>
  );
}
