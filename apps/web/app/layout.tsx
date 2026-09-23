import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SetuNER — Road Accessibility & Relief Logistics",
  description:
    "Flood accessibility forecasting and relief logistics for the Barak Valley corridor, Assam.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      {/* Explicit light ground: every screen is designed on white, and a
          browser in dark mode otherwise paints dark behind grey text. */}
      <body className="bg-white text-gray-900">{children}</body>
    </html>
  );
}
