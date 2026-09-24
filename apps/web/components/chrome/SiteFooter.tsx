/**
 * Footer: sparse, mono, one hairline rule. Carries the data attribution,
 * which is an obligation rather than a decoration -- OpenStreetMap's licence
 * requires it, and the government sources deserve naming.
 */

const SOURCES = [
  { label: "ASDMA DRIMS", detail: "daily flood reports" },
  { label: "NASA GPM IMERG", detail: "daily rainfall" },
  { label: "OpenStreetMap", detail: "roads, ODbL" },
  { label: "Copernicus DEM", detail: "terrain" },
];

export default function SiteFooter() {
  return (
    <footer className="mt-section border-t border-white/60 bg-white/30 backdrop-blur-xl">
      <div className="mx-auto grid max-w-page gap-8 px-6 py-10 font-mono text-micro text-muted sm:grid-cols-3">
        <div>
          <p className="uppercase text-ink">SetuNER</p>
          <p className="mt-2 max-w-xs leading-relaxed">
            Road accessibility forecasting and relief logistics for flood-prone Assam.
            A personal engineering project, not an official advisory service.
          </p>
        </div>

        <div>
          <p className="uppercase text-ink">Built on</p>
          <ul className="mt-2 space-y-1">
            {SOURCES.map((s) => (
              <li key={s.label}>
                <span className="text-ink">{s.label}</span> · {s.detail}
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="uppercase text-ink">Status</p>
          <ul className="mt-2 space-y-1">
            <li>
              <a
                className="hover:text-accent"
                href="https://setuner-api.onrender.com/docs"
                target="_blank"
                rel="noreferrer"
              >
                API reference ↗
              </a>
            </li>
            <li>
              <a
                className="hover:text-accent"
                href="https://setuner-api.onrender.com/api/v1/health/ready"
                target="_blank"
                rel="noreferrer"
              >
                Readiness check ↗
              </a>
            </li>
            <li>
              <a
                className="hover:text-accent"
                href="https://github.com/mKs2609/setu_ner"
                target="_blank"
                rel="noreferrer"
              >
                Source ↗
              </a>
            </li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
