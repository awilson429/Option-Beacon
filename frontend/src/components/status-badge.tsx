import { Circle } from "lucide-react";

const tone: Record<string, string> = {
  CALL: "border-slate-600 bg-transparent text-slate-300",
  PUT: "border-slate-600 bg-transparent text-slate-300",
  READY: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  TRIGGERED: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  LIVE: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  OPEN: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  STALE: "border-amber-400/40 bg-amber-400/10 text-amber-100",
  "STALE DATA": "border-amber-400/40 bg-amber-400/10 text-amber-100",
  CLOSED: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  SHADOW: "border-cyan-400/25 bg-cyan-400/10 text-cyan-200",
  TAKE: "border-emerald-400/40 bg-emerald-400/10 text-emerald-300",
  PASS: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  BLOCKED: "border-dashed border-rose-300/50 bg-transparent text-rose-100",
  REJECTED: "border-rose-400/35 bg-rose-400/10 text-rose-200",
  UNAVAILABLE: "border-slate-500/30 bg-slate-500/10 text-slate-400",
  "NO SETUP": "border-slate-500/30 bg-slate-500/10 text-slate-400",
  WAIT: "border-dotted border-amber-300/50 bg-transparent text-amber-100",
  FRESH: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  HEALTHY: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  CONNECTED: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  DISCONNECTED: "border-rose-400/35 bg-rose-400/10 text-rose-200",
  DEGRADED: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  COMPLETED: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  PROTECTED: "border-cyan-400/25 bg-cyan-400/10 text-cyan-200",
  DATA_UNSAFE: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  CURRENT: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  SCANNING: "border-cyan-400/25 bg-cyan-400/10 text-cyan-200",
  REFRESHING: "border-cyan-400/25 bg-cyan-400/10 text-cyan-200",
};

export function StatusBadge({ value, dot = false, muted = false }: { value?: string | null; dot?: boolean; muted?: boolean }) {
  const label = (value || "UNAVAILABLE").replaceAll("_", " ").toUpperCase();
  const style = muted ? "border-slate-500/40 bg-slate-500/10 text-slate-300" : tone[label] || (label.includes("RANGE") || label.includes("FORMING") || label.includes("WATCHING")
    ? "border-amber-400/25 bg-amber-400/10 text-amber-200"
    : "border-slate-500/30 bg-slate-500/10 text-slate-300");
  return <span className={`badge ${style}`}>{dot && <Circle aria-hidden size={6} fill="currentColor" />}{label}</span>;
}
