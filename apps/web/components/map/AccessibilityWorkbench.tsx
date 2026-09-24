"use client";

/**
 * The accessibility screen's client half: the model panel, the map, and the
 * explanation for whichever road was clicked.
 */

import { useState } from "react";

import RoadWhy from "@/components/explain/RoadWhy";
import AccessibilityMap from "./AccessibilityMap";
import ModelPanel from "./ModelPanel";

export default function AccessibilityWorkbench() {
  const [roadId, setRoadId] = useState<number | null>(null);

  return (
    <div className="flex flex-1 flex-col md:flex-row md:overflow-hidden">
      <aside className="w-full border-line md:w-[28rem] md:overflow-y-auto md:border-r">
        <ModelPanel />
      </aside>
      <div className="relative h-[60vh] flex-1 md:h-auto">
        <AccessibilityMap initialMetric="current_accessibility" onSelectRoad={setRoadId} />
        {roadId !== null && (
          <div className="absolute right-3 top-14 z-10 max-h-[80%] w-80 overflow-y-auto">
            <RoadWhy roadId={roadId} onClose={() => setRoadId(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
