import AccessibilityMap from "@/components/map/AccessibilityMap";

export default function DashboardPage() {
  return (
    <main className="h-screen w-screen flex flex-col">
      <header className="wash border-b border-line px-6 py-5">
        <h1 className="text-[28px] font-extralight leading-tight tracking-[-0.02em]">Barak Valley Corridor</h1>
        <p className="mt-1 text-caption text-muted">
          Roads colored by baseline accessibility. Red = worst, green = best, gray = not yet scored.
        </p>
      </header>
      <div className="flex-1">
        <AccessibilityMap />
      </div>
    </main>
  );
}