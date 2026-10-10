import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import SiteFooter from "@/components/chrome/SiteFooter";
import SiteNav from "@/components/chrome/SiteNav";
import "./globals.css";

/**
 * Fonts are self-hosted by next/font at build time: no request to Google at
 * runtime, no layout shift while a webfont loads, and nothing to fail on a
 * slow connection. Inter stands in for the reference's NB International Pro,
 * which is commercially licensed.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["300", "400", "500", "700"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

/**
 * `metadataBase` is what turns the relative card path into the absolute URL a
 * link preview needs; without it Next emits a relative one and every scraper
 * ignores it. `app/icon.svg` and `app/opengraph-image.jpg` are picked up by
 * filename, so they are not listed here.
 */
export const metadata: Metadata = {
  metadataBase: new URL("https://setu-ner-web.vercel.app"),
  title: "SetuNER — Road Accessibility & Relief Logistics",
  description:
    "Flood accessibility forecasting and relief logistics for the Barak Valley corridor, Assam.",
  openGraph: {
    type: "website",
    siteName: "SetuNER",
    url: "/",
    title: "SetuNER — which roads will still work tomorrow",
    description:
      "Flood accessibility forecasting and relief logistics for the Barak Valley corridor, Assam. Built from government reports, satellite rainfall and terrain, with every number traceable to its source.",
  },
  twitter: {
    card: "summary_large_image",
    title: "SetuNER — which roads will still work tomorrow",
    description:
      "Flood accessibility forecasting and relief logistics for the Barak Valley corridor, Assam.",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      {/* The canvas is stated on the body, not left to the browser: a dark
          system theme behind unstyled text is how the old build produced
          grey-on-black. */}
      <body className="min-h-screen bg-canvas font-sans text-ink antialiased">
        <SiteNav />
        <main className="min-h-[60vh]">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
