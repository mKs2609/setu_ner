/**
 * What a map says when it has nothing to show.
 *
 * WHY THIS EXISTS
 * All three workbench maps rendered their legend unconditionally, so an
 * empty map came with a key to markers that were not there -- "Clear, Slow,
 * Blocked" over an empty corridor, or "Depot, Circle fully supplied, Route
 * used" before any plan had been run. A legend for nothing is worse than no
 * legend: it tells a reader that symbols exist and they cannot find them,
 * which reads as a page that failed to load.
 *
 * So the legend is now conditional, and this takes its place: the same card,
 * in the same corner, saying what will appear here and -- where the reason is
 * not obvious -- why there is nothing yet.
 *
 * Server-rendered, no client JavaScript, and readable before anything
 * hydrates.
 */

export default function EmptyMap({
  title,
  children,
}: {
  /** What this map shows, when it has something: "Field reports". */
  title: string;
  /** Why it is empty, and what would fill it. One or two short sentences. */
  children: React.ReactNode;
}) {
  return (
    <div className="pointer-events-none absolute bottom-4 left-4 card max-w-[17rem] px-4 py-3">
      <p className="font-mono text-micro uppercase tracking-[0.14em] text-muted">{title}</p>
      <div className="mt-1.5 text-caption leading-snug text-muted">{children}</div>
    </div>
  );
}
