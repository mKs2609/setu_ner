"use client";

/**
 * The field-report screen: submit on the left, what everyone has reported on
 * the right.
 *
 * The panel shows the fused view of whatever road was last touched -- the
 * road you just reported on, or one clicked on the map -- with the crowd
 * consensus and the historical baseline side by side and clearly labelled as
 * different things. Collapsing them into one number would be easier to read
 * and would destroy the distinction the whole project rests on.
 */

import { useCallback, useEffect, useState } from "react";

import {
  fetchRecentReports,
  fetchRoadReports,
  getReporterId,
  type FieldReportAck,
  type RoadReportView,
  type StoredReport,
} from "@/lib/api";
import ReportForm from "./ReportForm";
import ReportsMap from "./ReportsMap";

const STATUS_STYLES: Record<string, string> = {
  clear: "bg-accent-wash text-accent ring-green-200",
  slow: "bg-caution/10 text-caution ring-caution/30",
  blocked: "bg-alert/10 text-alert ring-alert/30",
};

export default function FieldReportsWorkbench() {
  const [reporterId, setReporterId] = useState("");
  const [reports, setReports] = useState<StoredReport[]>([]);
  const [lastAck, setLastAck] = useState<FieldReportAck | null>(null);
  const [roadView, setRoadView] = useState<RoadReportView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReporterId(getReporterId());
  }, []);

  const refresh = useCallback(async () => {
    try {
      setReports(await fetchRecentReports(200));
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? `${e.message} — is the API running on port 8000?`
          : "Could not reach the API."
      );
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const showRoad = useCallback(async (roadId: number) => {
    try {
      setRoadView(await fetchRoadReports(roadId));
    } catch {
      setRoadView(null);
    }
  }, []);

  const handleSubmitted = useCallback(
    async (ack: FieldReportAck) => {
      setLastAck(ack);
      await refresh();
      if (ack.road_id) await showRoad(ack.road_id);
    },
    [refresh, showRoad]
  );

  const fused = roadView?.field_reported;

  return (
    <div className="grid grid-cols-1 md:h-full md:grid-cols-[24rem_1fr]">
      <div className="flex flex-col gap-4 border-b border-line bg-surface p-4 md:h-full md:overflow-y-auto md:border-b-0 md:border-r">
        <div>
          <h2 className="text-sm font-semibold text-ink">Report a road</h2>
          <p className="mt-0.5 text-xs leading-snug text-muted">
            Official sensors are sparse across the region. What people on the ground
            see is how the gap gets filled.
          </p>
        </div>

        {reporterId && <ReportForm reporterId={reporterId} onSubmitted={handleSubmitted} />}

        {lastAck && (
          <div className="space-y-2 card p-3">
            <div className="text-xs font-semibold text-ink">Report received</div>
            <p className="text-xs leading-snug text-muted">
              {lastAck.counted_in_fusion ? (
                <>
                  Matched to road <b>{lastAck.road_id}</b>, {lastAck.snapped_distance_m} m
                  away.
                </>
              ) : (
                <>
                  This landed <b>{Math.round((lastAck.snapped_distance_m ?? 0) / 1000)} km</b>{" "}
                  from any road in the corridor, so it is stored but not counted. It is
                  kept rather than discarded, because reports from outside the mapped
                  area are worth seeing.
                </>
              )}
            </p>
            <p className="text-xs leading-snug text-muted">
              {lastAck.trust_explanation} Your score is now{" "}
              <b>{lastAck.reporter_trust_score}</b>.
            </p>

            {lastAck.independent_evidence.evidence.length > 0 ? (
              <div className="rounded bg-surface p-2">
                <div className="text-[11px] font-semibold text-ink">
                  Checked against official hazard data
                </div>
                <ul className="mt-1 space-y-0.5">
                  {lastAck.independent_evidence.evidence.map((e) => (
                    <li key={e.kind} className="text-[11px] leading-snug text-muted">
                      • {e.detail}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-[11px] leading-snug text-muted">
                No official hazard data bears on that road right now. That is not held
                against the report — the daily bulletin is district-level and routinely
                behind what someone on the road can see.
              </p>
            )}
          </div>
        )}

        {roadView && fused && (
          <div className="space-y-2 card p-3">
            <div className="text-xs font-semibold text-ink">
              Road {roadView.road_id}
              {roadView.road.district ? ` — ${roadView.road.district}` : ""}
            </div>

            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted">
                What the ground says
              </div>
              {fused.status ? (
                <div
                  className={`mt-1 inline-block rounded px-2 py-1 text-xs font-semibold uppercase ring-1 ${
                    STATUS_STYLES[fused.status]
                  }`}
                >
                  {fused.status} · {Math.round(fused.confidence * 100)}% agreement
                </div>
              ) : (
                <div className="mt-1 text-xs text-muted">No reports in the last 24 h.</div>
              )}
              <div className="mt-1 text-[11px] text-muted">
                From {fused.report_count} report{fused.report_count === 1 ? "" : "s"} in the
                last {fused.window_hours} h, weighted by reporter trust and how recent each
                one is.
              </div>
            </div>

            <div className="border-t border-line pt-2">
              <div className="text-[11px] uppercase tracking-wide text-muted">
                Historical baseline
              </div>
              <div className="text-sm font-semibold text-ink">
                {roadView.road.baseline_accessibility != null
                  ? roadView.road.baseline_accessibility.toFixed(2)
                  : "not scored"}
              </div>
              <div className="text-[11px] leading-snug text-muted">
                From 2025 district flood severity — a different thing from the live
                reports above, and deliberately not merged with them.
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded bg-alert/10 p-2.5 text-xs leading-snug text-alert ring-1 ring-alert/30">
            {error}
          </div>
        )}

        {reporterId && (
          <p className="text-[11px] leading-snug text-muted">
            You are <code className="text-[10px]">{reporterId.slice(0, 20)}…</code> — an id
            this browser made up and kept. No name, phone number or account is asked for or
            stored.
          </p>
        )}
      </div>

      <div className="relative h-[26rem] md:h-full">
        <ReportsMap reports={reports} onSelect={showRoad} />
      </div>
    </div>
  );
}
