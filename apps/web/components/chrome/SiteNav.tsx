"use client";

/**
 * Site-wide header. Floats on the canvas with a hairline rule, no fill, no
 * shadow: the reference's "nav sits on the image" treatment, made legible on
 * scroll by a translucent backdrop rather than a solid bar.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/accessibility", label: "Forecast" },
  { href: "/logistics", label: "Supply" },
  { href: "/scenarios", label: "Scenarios" },
  { href: "/field-reports", label: "Reports" },
  { href: "/recommendations", label: "Records" },
];

export default function SiteNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-white/50 bg-white/40 backdrop-blur-xl supports-[backdrop-filter]:bg-white/40">
      <nav className="mx-auto flex max-w-page items-center justify-between gap-6 px-6 py-4">
        <Link href="/" className="group flex items-baseline gap-2">
          <span className="text-ui font-medium tracking-tight text-ink">SetuNER</span>
          <span className="hidden font-mono text-micro uppercase text-muted sm:inline">
            Barak Valley · Assam
          </span>
        </Link>

        <ul className="flex items-center gap-1 overflow-x-auto font-mono text-caption">
          {LINKS.map((l) => {
            const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <li key={l.href}>
                <Link
                  href={l.href}
                  className={`block whitespace-nowrap rounded px-2.5 py-1.5 transition-colors ${
                    active
                      ? "bg-accent text-white"
                      : "text-ink hover:bg-accent-wash/60 hover:text-accent"
                  }`}
                >
                  {l.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
