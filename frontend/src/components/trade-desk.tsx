"use client";

import {Activity,Clock3,Database,HeartPulse,RefreshCw,ScanSearch,WifiOff} from "lucide-react";
import Link from "next/link";
import {useLiveSnapshot} from "@/hooks/use-options-data";
import {label,money,number,percent,timestamp} from "@/lib/format";
import type {ActiveTrade,LiveSnapshot,LiveSymbolSnapshot,TradeRow} from "@/lib/types";
import {StatusBadge} from "./status-badge";

const indicatorName=(key:string)=>key.replaceAll("_"," ").replace(/\bema\b/i,"EMA").replace(/\brsi\b/i,"RSI").replace(/\bvwap\b/i,"VWAP");
const outcomeTone=(value?:number|null)=>value==null?"text-slate-400":value>=0?"text-emerald-300":"text-rose-300";
const clock=(value?:string|null)=>timestamp(value).replace(/:\d{2} /," ");
const healthTone=(value:string)=>{
  const v=value.toLowerCase();
  if(["connected","fresh","healthy","current","scanning","persisted","open","ok","ready"].includes(v)) return "text-emerald-300";
  if(["stale","degraded","wait","warning","partial"].includes(v)) return "text-amber-200";
  if(["disconnected","unavailable","rejected","blocked","error","failed","offline"].includes(v)) return "text-rose-200";
  return "text-slate-200";
};

function CompactEmpty({title,children}:{title:string;children:string}){
  return <p className="px-3 py-2 text-[11px] text-slate-500"><span className="font-semibold uppercase tracking-[.12em] text-slate-400">{title}</span> · {children}</p>;
}

function Chip({label:name,value}:{label:string;value:string}){
  return <div className="min-w-[7.5rem] flex-1 px-2.5 py-1.5"><p className="metric-label">{name}</p><p className={`mt-0.5 truncate text-[11px] font-semibold ${healthTone(value)}`}>{label(value)}</p></div>;
}

function actionState(item:LiveSymbolSnapshot){
  const primary=item.latest_decisions.find(d=>d.data_status==="persisted"&&d.state==="TAKE")||item.latest_decisions.find(d=>d.data_status==="persisted");
  return primary?.state||item.observation?.qualification_state||(!item.scanner.setup&&!item.observation?"NO SETUP":item.scanner.signal_state)||"UNAVAILABLE";
}

function TerminalHeader({data,degraded,refreshing,refresh}:{data:LiveSnapshot;degraded:boolean;refreshing:boolean;refresh:()=>void}){
  const connection=degraded?"Degraded":"Connected";
  const provenance=data.provenance.data_status==="persisted"?"Ready":"Not ready";
  const stale=data.market.freshness==="stale"||data.system.stale_or_missing.length>0;
  return <>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="eyebrow text-violet-300">OptionBeacon</p>
        <h1 className="mt-1 text-lg font-semibold tracking-[-.03em] sm:text-xl">Market Command</h1>
        <p className="mt-1 font-mono text-[10px] text-slate-600">snapshot {data.snapshot_id}</p>
      </div>
      <button type="button" onClick={refresh} disabled={refreshing} className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.11em] text-slate-300 disabled:opacity-50">
        <RefreshCw size={13} className={refreshing?"animate-spin":""} aria-hidden/>Refresh
      </button>
    </div>
    <section aria-label="Terminal status" className="mt-3 flex flex-wrap overflow-hidden rounded-lg border border-slate-800 bg-slate-800/80">
      {[["API",connection],["Worker",data.system.state.worker_status],["Scanner",data.scanner.status],["Database",data.system.state.database],["Freshness",data.market.freshness],["SPY",data.system.coverage.SPY],["QQQ",data.system.coverage.QQQ],["Provenance",provenance]].map(([name,value])=><Chip key={name} label={name} value={value}/>)}
    </section>
    {degraded&&<div role="alert" className="mt-2 flex items-center gap-2 rounded-md border border-rose-400/25 bg-rose-400/[.08] px-3 py-2 text-xs text-rose-100"><WifiOff size={14} aria-hidden/>Backend connection degraded. Showing the last valid authoritative snapshot.</div>}
    {stale&&<div role="alert" className="mt-2 flex items-center gap-2 rounded-md border border-amber-400/25 bg-amber-400/[.08] px-3 py-2 text-xs text-amber-100"><Clock3 size={14} aria-hidden/>Authoritative data is stale{data.system.stale_or_missing.length?`: ${data.system.stale_or_missing.join(", ")}`:"."}</div>}
  </>;
}

function SetupCard({item}:{item:LiveSymbolSnapshot}){
  const observation=item.observation;
  const decisions=item.latest_decisions.filter(d=>d.data_status==="persisted");
  const primary=decisions.find(d=>d.state==="TAKE")||decisions[0];
  const state=actionState(item);
  const indicators=Object.entries(observation?.indicators||{}).filter(([,v])=>v!==null&&v!==undefined).slice(0,10);
  const price=observation?.underlying_price??item.scanner.underlying_price;
  const score=observation?.total_score??item.scanner.score;
  const setup=item.scanner.setup;
  const frame=state==="TAKE"?"border-emerald-400/40 bg-emerald-950/20":state==="REJECTED"||state==="BLOCKED"?"border-rose-400/30":state==="STALE"||state==="WAIT"?"border-amber-400/30":"border-slate-800";
  return <article data-testid={`setup-${item.symbol}`} aria-label={`${item.symbol} ${state}`} className={`surface-tight min-w-0 overflow-hidden ${frame}`}>
    <header className="flex items-start justify-between gap-3 px-3.5 py-3">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-2xl font-black tracking-tight">{item.symbol}</h2>
          <StatusBadge value={item.scanner.direction}/>
          <StatusBadge value={state}/>
        </div>
        <p className="mt-1 text-[11px] font-semibold text-slate-300">{label(setup)} · {label(item.scanner.freshness)} · {clock(observation?.observed_at??item.scanner.observed_at)}</p>
      </div>
      <div className="text-right">
        <p className="metric-label">Score</p>
        <p className={`font-mono font-black tabular-nums leading-none ${score==null?"text-lg text-slate-500":state==="TAKE"?"text-3xl text-emerald-300":"text-3xl text-slate-100"}`}>{number(score,1)}</p>
      </div>
    </header>
    <div className="grid grid-cols-2 gap-x-4 border-t border-slate-800/80 px-3.5 py-3">
      <div><p className="metric-label">Price</p><p className="metric-value text-base">{money(price)}</p></div>
      <div><p className="metric-label">Rationale</p><p className="mt-1 text-xs font-semibold text-slate-200">{label(primary?.reason_code??observation?.reason_code)}</p></div>
    </div>
    <p className="px-3.5 pb-3 text-[11px] leading-5 text-slate-500">{primary?.explanation??(observation?.explanation as string|undefined)??"No authoritative decision explanation is available."}</p>
    {indicators.length>0?<ul className="grid grid-cols-2 gap-px border-t border-slate-800 bg-slate-800/80 sm:grid-cols-4">{indicators.map(([key,v])=><li key={key} className="bg-[#0c111d] px-3.5 py-2"><p className="metric-label">{indicatorName(key)}</p><p className="font-mono text-xs text-slate-200">{number(v,3)}</p></li>)}</ul>:<p className="border-t border-slate-800 px-3.5 py-2 text-[11px] text-slate-600">Persisted indicator values unavailable. Nothing has been reconstructed in the browser.</p>}
  </article>;
}

function Positions({trades}:{trades:ActiveTrade[]}){
  return <section className="surface-tight overflow-hidden" aria-labelledby="positions-heading">
    <header className="flex items-center gap-2 border-b border-slate-800 px-3.5 py-2">
      <Activity size={14} className="text-violet-300" aria-hidden/>
      <h2 id="positions-heading" className="text-sm font-semibold">Active positions</h2>
      <span className="ml-auto text-[10px] uppercase tracking-[.12em] text-slate-500">{trades.length?`${trades.length} open`:"None"}</span>
    </header>
    {trades.length===0?<CompactEmpty title="No active positions">The authoritative engine has no open positions.</CompactEmpty>:<div className="divide-y divide-slate-800">{trades.map(t=>{
      const pnlAuthoritative=t.unrealized_pnl!=null&&t.management_data_status==="persisted";
      return <article key={t.id} className="px-3.5 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <strong className="text-sm">{t.symbol||"Unknown"}</strong>
          <StatusBadge value={t.direction}/>
          <StatusBadge value={t.status}/>
          {t.exit_state||t.exit_label?<StatusBadge value={t.exit_state||t.exit_label}/>:null}
          {t.breakeven_state?<StatusBadge value={t.breakeven_state}/>:null}
          <span className="ml-auto font-mono text-[9px] text-slate-600">{t.id}</span>
        </div>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-4 xl:grid-cols-7">
          <div><dt className="metric-label">Entry / mark</dt><dd className="text-xs font-semibold tabular-nums">{money(t.underlying_entry??t.entry_price)} / {money(t.latest_underlying??t.last_price)}</dd></div>
          <div><dt className="metric-label">Stop / T1</dt><dd className="text-xs font-semibold tabular-nums">{money(t.stop)} / {money(t.target_1)}</dd></div>
          <div><dt className="metric-label">Hold</dt><dd className="text-xs font-semibold">{t.time_in_trade_seconds==null?"Unavailable":`${Math.floor(t.time_in_trade_seconds/60)}m`}</dd></div>
          <div><dt className="metric-label">P&amp;L</dt><dd className={`text-xs font-semibold tabular-nums ${pnlAuthoritative?outcomeTone(t.unrealized_pnl):"text-slate-400"}`}>{pnlAuthoritative?money(t.unrealized_pnl):"Unavailable"}</dd></div>
          <div><dt className="metric-label">Return</dt><dd className="text-xs font-semibold tabular-nums">{pnlAuthoritative?percent(t.unrealized_return_pct):"Unavailable"}</dd></div>
          <div><dt className="metric-label">Lifecycle</dt><dd className="text-xs font-semibold">{label(t.exit_state||t.thesis_state)}</dd></div>
          <div><dt className="metric-label">Management</dt><dd className="text-xs font-semibold">{label(t.management_data_status)}</dd></div>
        </dl>
      </article>;
    })}</div>}
  </section>;
}

function DecisionFeed({data}:{data:LiveSnapshot}){
  return <section className="surface-tight overflow-hidden" aria-labelledby="decisions-heading">
    <header className="flex items-center gap-2 border-b border-slate-800 px-3.5 py-2">
      <ScanSearch size={14} className="text-violet-300" aria-hidden/>
      <h2 id="decisions-heading" className="text-sm font-semibold">Decisions</h2>
    </header>
    {data.decisions.length===0?<CompactEmpty title="No recent decisions">No persisted lane decision is available.</CompactEmpty>:<ul className="divide-y divide-slate-800">{data.decisions.map((row,i)=>{
      const take=row.action==="TAKE";
      return <li key={row.decision_id??`${row.opportunity_id}:${i}`} className={`grid grid-cols-[4.5rem_2.4rem_1fr_auto] items-center gap-2 px-3.5 py-2 text-xs sm:grid-cols-[4.5rem_2.4rem_5.5rem_1fr_auto_auto] ${take?"bg-emerald-950/25":""}`}>
        <span className="font-mono text-[10px] text-slate-500">{clock(row.timestamp)}</span>
        <strong>{row.symbol}</strong>
        <span className="hidden text-slate-400 sm:inline">{label(row.setup)} · {label(row.direction)}</span>
        <span className="min-w-0 truncate font-semibold text-slate-300 sm:col-auto">{label(row.reason_code)}</span>
        <StatusBadge value={row.action}/>
        <span className="hidden font-mono text-slate-300 sm:inline">{number(row.score,1)}</span>
      </li>;
    })}</ul>}
  </section>;
}

function RecentTrades({trades}:{trades:TradeRow[]}){
  return <section className="surface-tight overflow-hidden" aria-labelledby="recent-heading">
    <header className="flex items-center gap-2 border-b border-slate-800 px-3.5 py-2">
      <Activity size={14} className="text-violet-300" aria-hidden/>
      <div><h2 id="recent-heading" className="text-sm font-semibold">Recent trades</h2><p className="sr-only">Compact authoritative history</p></div>
    </header>
    {trades.length===0?<CompactEmpty title="No recent trades">No completed authoritative trade is available.</CompactEmpty>:<ul className="divide-y divide-slate-800">{trades.slice(0,8).map(t=><li key={t.id} className="grid grid-cols-[4.5rem_1fr_auto] items-center gap-2 px-3.5 py-2 sm:grid-cols-[4.5rem_2.5rem_1fr_auto]">
      <span className="font-mono text-[10px] text-slate-600">{clock(t.closed_at??t.opened_at)}</span>
      <strong className="text-xs">{t.symbol??"Unknown"}</strong>
      <span className="hidden min-w-0 truncate text-[11px] text-slate-500 sm:inline">{label(t.direction)} · {money(t.entry_price)} → {money(t.exit_price)} · {label(t.exit_reason??t.status)}</span>
      <span className={`font-mono text-xs ${outcomeTone(t.realized_result)}`}>{money(t.realized_result)}</span>
    </li>)}</ul>}
  </section>;
}

function Health({data}:{data:LiveSnapshot}){
  const s=data.system.state;
  return <section className="surface-tight px-3.5 py-2" aria-labelledby="health-heading">
    <div className="flex flex-wrap items-center gap-2">
      <HeartPulse size={14} className="text-violet-300" aria-hidden/>
      <h2 id="health-heading" className="text-sm font-semibold">System & provenance</h2>
      <Link href="/diagnostics/live-snapshot" className="text-[10px] font-bold uppercase tracking-[.12em] text-violet-300">Diagnostics</Link>
    </div>
    <details className="mt-2">
      <summary className="cursor-pointer text-[11px] text-slate-500">Cycle and snapshot detail</summary>
      <dl className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div><dt className="metric-label">Cycle</dt><dd>{data.scanner.cycle_id??"Unavailable"}</dd></div>
        <div><dt className="metric-label">Completion</dt><dd>{label(data.scanner.cycle_completion_state)}</dd></div>
        <div><dt className="metric-label">Last success</dt><dd>{clock(data.scanner.last_successful_completed_cycle)}</dd></div>
        <div><dt className="metric-label">Snapshot</dt><dd className="font-mono text-[10px]">{data.snapshot_id}</dd></div>
        <div><dt className="metric-label">Updated</dt><dd>{clock(data.generated_at)}</dd></div>
        <div><dt className="metric-label">Market</dt><dd>{label(data.market.session_state)}</dd></div>
        <div><dt className="metric-label">Worker last success</dt><dd>{clock(s.worker_last_success)}</dd></div>
        <div><dt className="metric-label">Provider</dt><dd>{label(s.provider_status)}</dd></div>
      </dl>
    </details>
  </section>;
}

export function TradeDesk(){
  const snapshot=useLiveSnapshot();
  if(snapshot.isLoading&&!snapshot.data) return <div aria-label="Loading trading terminal" className="mx-auto max-w-[1680px] p-4"><div className="skeleton h-16"/><div className="mt-3 grid gap-3 lg:grid-cols-2"><div className="skeleton h-52"/><div className="skeleton h-52"/></div></div>;
  if(snapshot.error&&!snapshot.data) return <div role="alert" className="m-4 surface-tight p-6 text-center"><WifiOff className="mx-auto text-rose-300" aria-hidden/><h1 className="mt-3 text-lg font-bold">OptionBeacon backend disconnected</h1><p className="mt-2 text-sm text-slate-500">No authoritative snapshot is available. Trading values are intentionally hidden.</p><button type="button" onClick={()=>snapshot.mutate()} className="mt-4 rounded border border-slate-700 px-4 py-2 text-xs">Retry</button></div>;
  const data=snapshot.data!;
  return <div className="mx-auto max-w-[1680px] overflow-x-hidden px-3 py-4 sm:px-5 lg:px-6">
    <TerminalHeader data={data} degraded={Boolean(snapshot.error)} refreshing={snapshot.isValidating} refresh={()=>snapshot.mutate()}/>
    <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-2"><SetupCard item={data.symbols.SPY}/><SetupCard item={data.symbols.QQQ}/></div>
    <div className="mt-3 min-w-0"><Positions trades={data.active_trades}/></div>
    <div className="mt-3 grid min-w-0 items-start gap-3 xl:grid-cols-2"><DecisionFeed data={data}/><RecentTrades trades={data.recent_trades}/></div>
    <div className="mt-3"><Health data={data}/></div>
    <footer className="mt-3 flex items-center gap-2 text-[10px] text-slate-600"><Database size={12} aria-hidden/>Presentation only. No provider calls, strategy evaluation, or trading actions occur in this interface.</footer>
  </div>;
}
