"use client";

import { useLiveSnapshot } from "@/hooks/use-options-data";
import type { LiveSymbolSnapshot } from "@/lib/types";

const value=(input:unknown)=>input===null||input===undefined?"Unavailable":String(input);

function SymbolCard({item}:{item:LiveSymbolSnapshot}) {
  return <section data-testid={`snapshot-${item.symbol}`} className="rounded-xl border border-slate-800 bg-slate-950/50 p-5">
    <div className="flex items-center justify-between"><h2 className="text-lg font-bold text-white">{item.symbol}</h2><span className="text-xs uppercase text-violet-300">{item.data_status}</span></div>
    <dl className="mt-4 grid grid-cols-2 gap-3 text-xs"><div><dt className="text-slate-500">Price</dt><dd className="mt-1 text-slate-200">{value(item.observation?.underlying_price ?? item.scanner.underlying_price)}</dd></div><div><dt className="text-slate-500">Score</dt><dd className="mt-1 text-slate-200">{value(item.observation?.total_score ?? item.scanner.score)}</dd></div><div><dt className="text-slate-500">Setup</dt><dd className="mt-1 text-slate-200">{value(item.scanner.setup)}</dd></div><div><dt className="text-slate-500">Decision</dt><dd className="mt-1 text-slate-200">{value(item.observation?.qualification_state)}</dd></div></dl>
    {!item.observation&&<p className="mt-4 text-xs text-amber-200">Canonical observation unavailable; no value was inferred.</p>}
  </section>;
}

export function LiveSnapshotDebug() {
  const snapshot=useLiveSnapshot();
  if(snapshot.isLoading) return <div aria-label="Loading live snapshot" className="p-8 text-sm text-slate-400">Loading canonical snapshot…</div>;
  if(snapshot.error||!snapshot.data) return <div role="alert" className="m-8 rounded-xl border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200"><h1 className="font-bold">Backend unavailable</h1><p className="mt-2">The canonical live snapshot could not be loaded.</p><button onClick={()=>snapshot.mutate()} className="mt-4 rounded border border-red-300/30 px-3 py-1.5">Retry</button></div>;
  const data=snapshot.data;
  return <div className="space-y-6 p-5 sm:p-8">
    <header><p className="text-xs font-bold uppercase tracking-widest text-violet-300">Migration diagnostics · schema {data.schema_version}</p><h1 className="mt-2 text-2xl font-bold text-white">Canonical Live Snapshot</h1><p className="mt-2 text-sm text-slate-400">Read-only persisted state generated {new Date(data.generated_at).toLocaleString()}.</p></header>
    <div className="grid gap-4 md:grid-cols-2"><SymbolCard item={data.symbols.SPY}/><SymbolCard item={data.symbols.QQQ}/></div>
    <section className="grid gap-4 rounded-xl border border-slate-800 p-5 text-sm sm:grid-cols-4"><div><p className="text-slate-500">API</p><p className="text-emerald-300">Connected</p></div><div><p className="text-slate-500">Scanner</p><p>{data.scanner.status}</p></div><div><p className="text-slate-500">Cycle</p><p>{value(data.scanner.cycle_id)}</p></div><div><p className="text-slate-500">Freshness</p><p>{data.market.freshness}</p></div></section>
    {data.system.stale_or_missing.length>0&&<section role="alert" className="rounded-xl border border-amber-400/20 bg-amber-400/5 p-4 text-sm text-amber-100">Missing/stale: {data.system.stale_or_missing.join(", ")}</section>}
    <section><h2 className="text-sm font-bold uppercase tracking-wider text-slate-300">Recent decisions</h2>{data.decisions.length?<div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-slate-500"><tr><th>Symbol</th><th>Lane</th><th>Action</th><th>Score</th><th>Reason</th></tr></thead><tbody>{data.decisions.map((row,index)=><tr key={row.decision_id??`${row.opportunity_id}:${row.lane}:${index}`} className="border-t border-slate-800"><td>{row.symbol}</td><td>{row.lane}</td><td>{value(row.action)}</td><td>{value(row.score)}</td><td>{value(row.reason_code)}</td></tr>)}</tbody></table></div>:<p className="mt-3 text-sm text-slate-500">No persisted decisions available.</p>}</section>
    <section className="grid gap-4 md:grid-cols-2"><div className="rounded-xl border border-slate-800 p-5"><h2 className="font-bold">Active trades</h2><p className="mt-2 text-2xl">{data.active_trades.length}</p></div><div className="rounded-xl border border-slate-800 p-5"><h2 className="font-bold">Recent completed trades</h2><p className="mt-2 text-2xl">{data.recent_trades.length}</p></div></section>
  </div>;
}
