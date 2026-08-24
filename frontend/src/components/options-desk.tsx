"use client";

import { RefreshCw } from "lucide-react";
import { useComparison, useInstrumentData } from "@/hooks/use-options-data";
import { ComparisonTable } from "./comparison-table";
import { InstrumentPanel } from "./instrument-panel";

export function OptionsDesk() {
  const spy=useInstrumentData("SPY"); const qqq=useInstrumentData("QQQ"); const comparison=useComparison();
  const refresh=()=>Promise.all([spy.strategy.mutate(),spy.scalp.mutate(),spy.performance.mutate(),qqq.strategy.mutate(),qqq.scalp.mutate(),qqq.performance.mutate(),comparison.mutate()]);
  return <div className="mx-auto max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
    <div className="mb-6 flex items-end justify-between gap-4"><div><p className="eyebrow text-violet-300">Trade / Index options</p><h1 className="mt-2 text-2xl font-semibold tracking-[-.035em] sm:text-3xl">SPY / QQQ Options Desk</h1><p className="mt-2 max-w-xl text-xs leading-5 text-slate-500">Existing OptionBeacon strategy and isolated short-duration research, presented with equal weight.</p></div><button onClick={refresh} className="flex shrink-0 items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-[10px] font-bold uppercase tracking-[.11em] text-slate-300 hover:border-slate-500"><RefreshCw aria-hidden size={13}/>Refresh</button></div>
    <div className="grid items-start gap-5 xl:grid-cols-2"><InstrumentPanel symbol="SPY" {...spy}/><InstrumentPanel symbol="QQQ" {...qqq}/></div>
    <div className="mt-5"><ComparisonTable response={comparison}/></div>
  </div>;
}
