import { Circle } from "lucide-react";

const tone: Record<string, string> = {
  CALL: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
  PUT: "border-rose-400/25 bg-rose-400/10 text-rose-300",
  READY: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  TRIGGERED: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  LIVE: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  OPEN: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  STALE: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  CLOSED: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  SHADOW: "border-cyan-400/25 bg-cyan-400/10 text-cyan-200",
  TAKE: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  PASS: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  BLOCKED: "border-rose-400/25 bg-rose-400/10 text-rose-200",
  DATA_UNSAFE: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  CURRENT: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  SCANNING: "border-cyan-400/25 bg-cyan-400/10 text-cyan-200",
};

export function StatusBadge({ value, dot = false }: { value?: string | null; dot?: boolean }) {
  const label = (value || "UNAVAILABLE").replaceAll("_", " ").toUpperCase();
  const style = tone[label] || (label.includes("RANGE") || label.includes("FORMING") || label.includes("WATCHING")
    ? "border-amber-400/25 bg-amber-400/10 text-amber-200"
    : "border-slate-500/30 bg-slate-500/10 text-slate-300");
  return <span className={`badge ${style}`}>{dot && <Circle aria-hidden size={6} fill="currentColor" />}{label}</span>;
}
