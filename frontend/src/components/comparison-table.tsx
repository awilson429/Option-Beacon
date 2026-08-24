"use client";

import { ArrowLeftRight, Scale } from "lucide-react";
import type { SWRResponse } from "swr";
import { SectionError } from "./empty-state";
import { money, number, percent } from "@/lib/format";
import type { ComparisonResponse, PerformanceMetrics } from "@/lib/types";

const rows: [string,keyof PerformanceMetrics,(value?: number|null)=>string][] = [
  ["Triggered trades","triggered_trades",v=>number(v,0)], ["Win rate","win_rate",percent], ["Expectancy","expectancy",money],
  ["Profit factor","profit_factor",number], ["Net simulated P&L","net_simulated_pnl",money], ["Max drawdown","maximum_drawdown",money],
  ["Average hold","average_hold_minutes",v=>v==null?"Unavailable":`${number(v,1)}m`],
];

export function ComparisonTable({ response }: { response: SWRResponse<ComparisonResponse> }) {
  if (response.error) return <section className="surface p-5"><SectionError label="SPY vs QQQ comparison" retry={()=>response.mutate()}/></section>;
  if (!response.data) return <section aria-label="Loading comparison" className="surface p-5"><div className="skeleton h-5 w-64"/><div className="skeleton mt-5 h-52"/></section>;
  const spy=response.data.symbols.SPY || {}; const qqq=response.data.symbols.QQQ || {};
  const insufficient=[spy.evidence,qqq.evidence].some(value=>(value||"INSUFFICIENT").toUpperCase().includes("INSUFFICIENT"));
  return <section className="surface overflow-hidden" aria-labelledby="comparison-heading">
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 px-5 py-5 sm:px-6"><div><div className="flex items-center gap-2"><ArrowLeftRight aria-hidden size={15} className="text-violet-300"/><p className="eyebrow">Scalp research comparison</p></div><h2 id="comparison-heading" className="mt-2 text-lg font-semibold tracking-tight">SPY vs QQQ · normalized shadow evidence</h2></div><div className={`rounded-md border px-3 py-2 text-[10px] font-bold tracking-[.12em] ${insufficient?"border-amber-400/20 bg-amber-400/[.07] text-amber-200":"border-slate-700 text-slate-300"}`}>{insufficient?"NO WINNER · INSUFFICIENT EVIDENCE":"EVIDENCE AVAILABLE"}</div></header>
    <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left"><caption className="sr-only">Normalized SPY and QQQ scalp performance</caption><thead><tr className="border-b border-slate-800/80"><th className="px-5 py-3 text-[9px] font-semibold uppercase tracking-[.16em] text-slate-600 sm:px-6">Metric</th><th className="px-4 py-3 text-xs font-black tracking-[.1em]">SPY</th><th className="px-4 py-3 text-xs font-black tracking-[.1em]">QQQ</th></tr></thead><tbody>{rows.map(([name,key,format])=><tr key={key} className="border-b border-slate-800/50 last:border-0"><th scope="row" className="px-5 py-3 text-xs font-medium text-slate-500 sm:px-6">{name}</th><td className="px-4 py-3 font-mono text-sm font-semibold tabular-nums text-slate-200">{format(spy[key] as number|null|undefined)}</td><td className="px-4 py-3 font-mono text-sm font-semibold tabular-nums text-slate-200">{format(qqq[key] as number|null|undefined)}</td></tr>)}</tbody><tfoot><tr className="bg-slate-950/25"><th className="px-5 py-4 text-[10px] uppercase tracking-widest text-slate-600 sm:px-6">Evidence</th><td className="px-4 py-4 text-[10px] font-bold uppercase tracking-wider text-amber-200">{spy.evidence || "INSUFFICIENT"}</td><td className="px-4 py-4 text-[10px] font-bold uppercase tracking-wider text-amber-200">{qqq.evidence || "INSUFFICIENT"}</td></tr></tfoot></table></div>
    <footer className="flex items-start gap-2 border-t border-slate-800 px-5 py-3 text-[10px] leading-4 text-slate-600 sm:px-6"><Scale aria-hidden className="mt-0.5 shrink-0" size={12}/><span>{response.data.normalization}. Realistic simulated execution is primary; early samples are not treated as statistically meaningful.</span></footer>
  </section>;
}
