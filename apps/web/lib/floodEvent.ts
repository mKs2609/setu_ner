/**
 * The 2025 Barak Valley flood, as this project's own two sources recorded it.
 *
 * Rainfall is NASA IMERG over Cachar; `affected` is whether the ASDMA daily
 * report listed Cachar as flood-affected that day, with null meaning no
 * report was published -- unknown, never "no flood".
 *
 * Committed as data rather than fetched: it is a fixed historical window used
 * to explain the idea on the landing page, and it should render instantly
 * even when the API is asleep. Regenerate with the query in
 * docs/decisions/0014 if the record is ever reingested.
 */
export interface FloodEventDay {
  date: string;
  rain: number | null;
  affected: boolean | null;
}

export const CACHAR_JUNE_2025: FloodEventDay[] = [
  { date: "2025-05-24", rain: 6.4, affected: null },
  { date: "2025-05-25", rain: 46.6, affected: false },
  { date: "2025-05-26", rain: 17.7, affected: false },
  { date: "2025-05-27", rain: 1.9, affected: false },
  { date: "2025-05-28", rain: 20.3, affected: false },
  { date: "2025-05-29", rain: 40.4, affected: false },
  { date: "2025-05-30", rain: 33.8, affected: true },
  { date: "2025-05-31", rain: 89.7, affected: false },
  { date: "2025-06-01", rain: 32.0, affected: true },
  { date: "2025-06-02", rain: 11.8, affected: true },
  { date: "2025-06-03", rain: 4.1, affected: true },
  { date: "2025-06-04", rain: 4.6, affected: true },
  { date: "2025-06-05", rain: 3.8, affected: true },
  { date: "2025-06-06", rain: 4.6, affected: true },
  { date: "2025-06-07", rain: 0.8, affected: false },
  { date: "2025-06-08", rain: 0.1, affected: true },
  { date: "2025-06-09", rain: 0.1, affected: true },
  { date: "2025-06-10", rain: 11.0, affected: true },
  { date: "2025-06-11", rain: 1.5, affected: true },
  { date: "2025-06-12", rain: 0.3, affected: true },
  { date: "2025-06-13", rain: 6.2, affected: false },
  { date: "2025-06-14", rain: 13.1, affected: false },
  { date: "2025-06-15", rain: 41.9, affected: false },
  { date: "2025-06-16", rain: 24.6, affected: false },
  { date: "2025-06-17", rain: 22.4, affected: false },
  { date: "2025-06-18", rain: 5.2, affected: false }
];

/** The day the district first appeared in the report as flood-affected. */
export const FIRST_AFFECTED = "2025-05-30";
