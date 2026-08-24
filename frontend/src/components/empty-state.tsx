import { CircleDashed } from "lucide-react";

export function EmptyState({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="flex min-h-32 items-center gap-4 rounded-lg border border-dashed border-slate-700/80 bg-slate-950/20 px-5 py-6">
    <CircleDashed aria-hidden className="shrink-0 text-slate-600" size={22} />
    <div><p className="text-xs font-bold uppercase tracking-[.13em] text-slate-300">{title}</p><p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">{children}</p></div>
  </div>;
}

export function SectionError({ label, retry }: { label: string; retry: () => void }) {
  return <div role="alert" className="rounded-lg border border-rose-400/20 bg-rose-400/[.06] p-4">
    <p className="text-xs font-semibold text-rose-200">{label} unavailable</p>
    <p className="mt-1 text-xs text-slate-500">Other desk data will continue updating.</p>
    <button onClick={retry} className="mt-3 rounded-md border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:border-slate-500">Retry</button>
  </div>;
}
