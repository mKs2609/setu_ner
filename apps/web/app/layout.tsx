import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SIH26002 — NER Accessibility & Logistics Intelligence",
  description:
    "Dynamic accessibility forecasting and logistics optimization for the North Eastern Region.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
