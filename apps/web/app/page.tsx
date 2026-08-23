export default function Home() {
  return (
    <main className="p-8">
      <h1 className="text-2xl font-semibold">SIH26002 — NER Accessibility & Logistics Intelligence</h1>
      <p className="mt-2 text-gray-600">
        Scaffold stage. Real UI/UX pass comes after the core data → accessibility →
        optimization → explanation loop works end to end (see docs/decisions/0001).
      </p>
      <ul className="mt-4 list-disc pl-5 text-blue-700">
        <li><a href="/dashboard">/dashboard</a></li>
        <li><a href="/accessibility">/accessibility</a></li>
        <li><a href="/logistics">/logistics</a></li>
        <li><a href="/scenarios">/scenarios</a></li>
        <li><a href="/field-reports">/field-reports</a></li>
      </ul>
    </main>
  );
}
