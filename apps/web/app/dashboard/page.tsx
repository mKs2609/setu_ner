import AccessibilityMap from "@/components/map/AccessibilityMap";

export default function DashboardPage() {
  return (
    // Same shape as the other workbench screens: locked to the viewport from
    // md up, and free to stack and scroll below it. `w-screen` was the old
    // value and it overflows horizontally once a scrollbar exists.
    <main className="flex min-h-screen w-full flex-col md:h-screen md:overflow-hidden">
      <header className="wash border-b border-line px-4 py-4 md:px-6 md:py-5">
        <h1 className="text-[22px] font-extralight leading-tight tracking-[-0.02em] md:text-[28px]">
          Barak Valley Corridor
        </h1>
        <p className="mt-1 text-caption text-muted">
          Every road segment in the corridor, scored for tomorrow. Dark and dashed means cut
          off, amber degraded, green clear; grey is not scored at all.
        </p>
      </header>
      <div className="flex flex-1 flex-col md:overflow-hidden">
        <AccessibilityMap />
      </div>
    </main>
  );
}