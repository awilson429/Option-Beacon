export function Metric({ label, value, accent }: { label: string; value: React.ReactNode; accent?: string }) {
  return <div className="min-w-0"><span className="metric-label">{label}</span><strong className={`metric-value ${accent || ""}`}>{value}</strong></div>;
}
