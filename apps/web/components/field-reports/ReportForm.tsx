"use client";

/**
 * The report form.
 *
 * DESIGNED FOR SOMEONE STANDING IN THE RAIN
 * Three big status buttons, one location control, and a submit. The note is
 * optional and everything else is filled in for them. Anyone reporting a
 * washed-out road is doing it one-handed on a phone in bad conditions, and
 * every extra required field is a report that does not get sent.
 *
 * WHY MANUAL COORDINATES ARE OFFERED TOO
 * Not as a developer convenience. GPS fails indoors, under tree cover and in
 * the steep terrain this corridor is full of, and a control room relaying a
 * report from someone on a phone line has coordinates but no device fix.
 * Refusing the report because the browser could not get a lock would lose
 * exactly the reports that matter most.
 */

import { useState } from "react";

import { submitFieldReport, type FieldReportAck, type ReportStatus } from "@/lib/api";

const STATUS_CHOICES: { value: ReportStatus; label: string; hint: string; classes: string }[] = [
  {
    value: "clear",
    label: "Clear",
    hint: "Passable as normal",
    classes: "border-green-300 bg-green-50 text-green-900",
  },
  {
    value: "slow",
    label: "Slow",
    hint: "Passable but difficult",
    classes: "border-amber-300 bg-amber-50 text-amber-900",
  },
  {
    value: "blocked",
    label: "Blocked",
    hint: "Not passable at all",
    classes: "border-red-300 bg-red-50 text-red-900",
  },
];

export default function ReportForm({
  reporterId,
  onSubmitted,
}: {
  reporterId: string;
  onSubmitted: (ack: FieldReportAck) => void;
}) {
  const [status, setStatus] = useState<ReportStatus>("blocked");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [note, setNote] = useState("");
  const [locating, setLocating] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const useMyLocation = () => {
    setError(null);
    if (!navigator.geolocation) {
      setError("This browser cannot report a location. Enter coordinates instead.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(pos.coords.latitude.toFixed(6));
        setLon(pos.coords.longitude.toFixed(6));
        setLocating(false);
      },
      (err) => {
        setLocating(false);
        setError(
          `Could not get a location (${err.message}). Enter coordinates manually.`
        );
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  const submit = async () => {
    const latitude = Number(lat);
    const longitude = Number(lon);
    if (!lat || !lon || Number.isNaN(latitude) || Number.isNaN(longitude)) {
      setError("A location is needed before this can be sent.");
      return;
    }
    setSending(true);
    setError(null);
    try {
      const ack = await submitFieldReport({
        status,
        latitude,
        longitude,
        reporter_id: reporterId,
        note: note.trim() || null,
      });
      onSubmitted(ack);
      setNote("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the report.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1.5 block text-xs font-medium text-gray-700">
          What is the road like here?
        </label>
        <div className="grid grid-cols-3 gap-1.5">
          {STATUS_CHOICES.map((choice) => (
            <button
              key={choice.value}
              type="button"
              onClick={() => setStatus(choice.value)}
              className={`rounded-md border px-2 py-2.5 text-center transition ${
                status === choice.value
                  ? `${choice.classes} font-semibold`
                  : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              <div className="text-sm">{choice.label}</div>
              <div className="mt-0.5 text-[10px] leading-tight opacity-80">{choice.hint}</div>
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1.5 block text-xs font-medium text-gray-700">Where</label>
        <button
          type="button"
          onClick={useMyLocation}
          disabled={locating}
          className="w-full rounded-md border border-teal-300 bg-teal-50 px-3 py-2 text-sm font-medium text-teal-800 transition hover:bg-teal-100 disabled:opacity-60"
        >
          {locating ? "Finding you..." : "Use my location"}
        </button>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <input
            value={lat}
            onChange={(e) => setLat(e.target.value)}
            placeholder="Latitude"
            inputMode="decimal"
            className="rounded border border-gray-300 px-2 py-1.5 text-xs"
          />
          <input
            value={lon}
            onChange={(e) => setLon(e.target.value)}
            placeholder="Longitude"
            inputMode="decimal"
            className="rounded border border-gray-300 px-2 py-1.5 text-xs"
          />
        </div>
        <p className="mt-1 text-[11px] leading-snug text-gray-500">
          GPS fails under tree cover and in steep terrain, and a control room relaying a
          report by phone has coordinates but no device fix — so they can be typed in.
        </p>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-gray-700">
          Anything else? <span className="font-normal text-gray-500">(optional)</span>
        </label>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value.slice(0, 500))}
          rows={2}
          placeholder="Water over the road, knee deep"
          className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs"
        />
      </div>

      <button
        type="button"
        onClick={submit}
        disabled={sending}
        className="w-full rounded-md bg-teal-700 px-3 py-2.5 text-sm font-medium text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-gray-400"
      >
        {sending ? "Sending..." : "Send report"}
      </button>

      {error && (
        <div className="rounded-md bg-red-50 p-2.5 text-xs leading-snug text-red-800 ring-1 ring-red-200">
          {error}
        </div>
      )}
    </div>
  );
}
