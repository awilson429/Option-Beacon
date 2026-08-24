const states = ["IDLE", "WATCHING", "FORMING", "READY", "TRIGGERED", "EXTENDED", "INVALIDATED", "EXPIRED"];

export function ScalpLifecycle({ current }: { current?: string | null }) {
  const active = current?.toUpperCase();
  return <ol aria-label="Scalp setup progression" className="flex flex-wrap gap-1.5">
    {states.map((state, index) => <li key={state} className="flex items-center gap-1.5">
      <span aria-current={active === state ? "step" : undefined} className={`rounded-md border px-2 py-1 text-[9px] font-bold tracking-[.08em] ${active === state ? "border-cyan-400/40 bg-cyan-400/15 text-cyan-100" : "border-slate-800 bg-slate-950/30 text-slate-600"}`}>{state}</span>
      {index < states.length - 1 && <span aria-hidden className="text-[9px] text-slate-700">›</span>}
    </li>)}
  </ol>;
}
