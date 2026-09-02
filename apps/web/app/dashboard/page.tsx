import AccessibilityMap from "@/components/map/AccessibilityMap";

export default function DashboardPage() {
  return (
    <main className="h-screen w-screen flex flex-col">
      <header className="p-4 border-b border-gray-200">
        <h1 className="text-xl font-semibold">SetuNER — Barak Valley Corridor</h1>
        <p className="text-sm text-gray-600">
          Roads colored by baseline accessibility. Red = worst, green = best, gray = not yet scored.
        </p>
      </header>
      <div className="flex-1">
        <AccessibilityMap />
      </div>
    </main>
  );
}