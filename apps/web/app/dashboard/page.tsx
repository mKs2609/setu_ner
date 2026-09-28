import AccessibilityMap from "@/components/map/AccessibilityMap";

export default function DashboardPage() {
  return (
    <main className="h-screen w-screen flex flex-col">
      <header className="wash border-b border-line px-6 py-5">
        <h1 className="text-[28px] font-extralight leading-tight tracking-[-0.02em]">Barak Valley Corridor</h1>
        <p className="mt-1 text-caption text-muted">
          Every road segment in the corridor, scored for tomorrow. Dark and dashed means cut
          off, amber degraded, green clear; grey is not scored at all. The legend is bottom left.
        </p>
      </header>
      <div className="flex-1">
        <AccessibilityMap />
      </div>
    </main>
  );
}