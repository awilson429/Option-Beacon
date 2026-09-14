"use client";

import {Activity,Clock3,Database,HeartPulse,RefreshCw,ScanSearch,WifiOff} from "lucide-react";
import Link from "next/link";
import {useLiveSnapshot} from "@/hooks/use-options-data";
import {label,money,number,timestamp} from "@/lib/format";
import type {ActiveTrade,LiveSnapshot,LiveSymbolSnapshot,TradeRow} from "@/lib/types";
import {StatusBadge} from "./status-badge";

const indicatorName=(key:string)=>key.replaceAll("_"," ").replace(/\bema\b/i,"EMA").replace(/\brsi\b/i,"RSI").replace(/\bvwap\b/i,"VWAP");
const outcomeTone=(value?:number|null)=>value==null?"text-slate-400":value>=0?"text-emerald-300":"text-rose-300";
const clock=(value?:string|null)=>timestamp(value).replace(/:\d{2} /," ");
const lc=(value?:string|null)=>value?.trim().toLowerCase()??"";

function CompactEmpty({title,children}:{title:string;children:string}){
  return <p className="px-3 py-2 text-[11px] text-slate-500"><span className="font-semibold uppercase tracking-[.12em] text-slate-400">{title}</span> · {children}</p>;
}

function actionState(item:LiveSymbolSnapshot){
  const primary=item.latest_decisions.find(d=>d.data_status==="persisted"&&d.state==="TAKE")||item.latest_decisions.find(d=>d.data_status==="persisted");
  return primary?.state||item.observation?.qualification_state||(!item.scanner.setup&&!item.observation?"NO SETUP":item.scanner.signal_state)||"UNAVAILABLE";
}

export function isAuthoritativeStale(data:LiveSnapshot){
  return lc(data.market.freshness)==="stale"||lc(data.scanner.status)==="stale"||data.system.stale_or_missing.length>0;
}

function dataState(data:LiveSnapshot):"Current"|"Stale"|"Unavailable"{
  if(isAuthoritativeStale(data)) return "Stale";
  const freshness=lc(data.market.freshness);
  if(!freshness||freshness==="unavailable") return "Unavailable";
  if(freshness==="fresh"||freshness==="current") return "Current";
  return "Unavailable";
}

function sessionState(data:LiveSnapshot):"Open"|"Closed"|"Unknown"{
  const session=lc(data.market.session_state);
  if(session==="open") return "Open";
  if(session==="closed") return "Closed";
  return "Unknown";
}

function scannerState(data:LiveSnapshot):"Healthy"|"Stale"|"Degraded"{
  const status=lc(data.scanner.status);
  if(status==="stale") return "Stale";
  if(status==="degraded") return "Degraded";
  return "Healthy";
}

function coverageLabel(value?:string|null){
  const v=lc(value);
  if(["persisted","ready","available","current","fresh","covered"].includes(v)) return "Covered";
  if(["stale"].includes(v)) return "Stale";
  if(["unavailable","missing","none"].includes(v)||!v) return "Unavailable";
  return label(value);
}

function symbolFreshness(data:LiveSnapshot,item:LiveSymbolSnapshot):"Current"|"Stale"|"Unavailable"{
  if(isAuthoritativeStale(data)) return "Stale";
  if(lc(item.data_status)==="unavailable"||lc(item.scanner.freshness)==="unavailable") return "Unavailable";
  const freshness=lc(item.scanner.freshness||data.market.freshness);
  if(!freshness) return "Unavailable";
  if(freshness==="stale") return "Stale";
  if(freshness==="fresh"||freshness==="current") return "Current";
  return "Unavailable";
}

function toneOf(value:string){
  const v=value.toLowerCase();
  if(["connected","current","open","healthy","covered","ready"].includes(v)) return "ok" as const;
  if(["stale","degraded","unknown","wait"].includes(v)) return "warn" as const;
  return "bad" as const;
}

function ClusterItem({label:name,value}:{label:string;value:string}){
  const tone=toneOf(value);
  return <div className="flex items-center gap-1.5">
    <span className={`size-1.5 shrink-0 rounded-full ${tone==="ok"?"bg-emerald-400":tone==="warn"?"bg-amber-300":"bg-rose-400"}`} aria-hidden/>
    <span className="text-[10px] font-semibold uppercase tracking-[.12em] text-slate-500">{name}</span>
    <span className={`text-[11px] font-semibold ${tone==="ok"?"text-slate-200":tone==="warn"?"text-amber-100":"text-rose-100"}`}>{value}</span>
  </div>;
}

function TerminalHeader({data,disconnected,refreshing,refresh}:{data:LiveSnapshot;disconnected:boolean;refreshing:boolean;refresh:()=>void}){
  const connection=disconnected?"Disconnected":"Connected";
  const market=sessionState(data);
  const authoritative=dataState(data);
  const scanner=scannerState(data);
  const stale=authoritative==="Stale";
  const problems:[string,string][]=[];
  if(disconnected) problems.push(["Connection","Disconnected"]);
  if(stale) problems.push(["Data","Stale"]);
  if(scanner!=="Healthy") problems.push(["Scanner",scanner]);
  if(lc(data.system.state.worker_status)==="degraded") problems.push(["Worker","Degraded"]);
  if(!["connected","ok"].includes(lc(data.system.state.database))) problems.push(["Database",label(data.system.state.database)]);
  if(coverageLabel(data.system.coverage.SPY)!=="Covered") problems.push(["SPY",coverageLabel(data.system.coverage.SPY)]);
  if(coverageLabel(data.system.coverage.QQQ)!=="Covered") problems.push(["QQQ",coverageLabel(data.system.coverage.QQQ)]);
  if(lc(data.provenance.data_status)!=="persisted") problems.push(["Provenance","Not ready"]);
  return <>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="eyebrow text-violet-300">OptionBeacon</p>
        <h1 className="mt-1 text-lg font-semibold tracking-[-.03em] sm:text-xl">Market Command</h1>
      </div>
      <button type="button" onClick={refresh} disabled={refreshing} className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.11em] text-slate-300 disabled:opacity-50">
        <RefreshCw size={13} className={refreshing?"animate-spin":""} aria-hidden/>Refresh
      </button>
    </div>
    <section aria-label="Terminal status" className={`mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border px-3 py-2 ${problems.length?"border-amber-400/25 bg-amber-400/[.04]":"border-slate-800 bg-slate-800/80"}`}>
      <ClusterItem label="Connection" value={connection}/>
      <ClusterItem label="Market" value={market}/>
      <ClusterItem label="Data" value={authoritative}/>
      <ClusterItem label="Scanner" value={scanner}/>
    </section>
    {disconnected&&<div role="alert" className="mt-2 flex items-center gap-2 rounded-md border border-rose-400/25 bg-rose-400/[.08] px-3 py-2 text-xs text-rose-100"><WifiOff size={14} aria-hidden/>Backend disconnected. Showing the last valid authoritative snapshot.</div>}
    {stale&&<div role="alert" className="mt-2 flex items-center gap-2 rounded-md border border-amber-400/25 bg-amber-400/[.08] px-3 py-2 text-xs text-amber-100"><Clock3 size={14} aria-hidden/>Authoritative data is stale{data.system.stale_or_missing.length?`: ${data.system.stale_or_missing.join(", ")}`:"."} Last decision remains historical, not a live signal.</div>}
    {problems.filter(([name])=>!["Connection","Data","Scanner"].includes(name)).length>0&&<ul className="mt-2 flex flex-wrap gap-2">{problems.filter(([name])=>!["Connection","Data","Scanner"].includes(name)).map(([name,value])=><li key={name} className="rounded border border-amber-400/20 px-2 py-1 text-[10px] font-semibold uppercase tracking-[.12em] text-amber-100">{name} {value}</li>)}</ul>}
  </>;
}

function SetupCard({item,stale,data}:{item:LiveSymbolSnapshot;stale:boolean;data:LiveSnapshot}){
  const observation=item.observation;
  const decisions=item.latest_decisions.filter(d=>d.data_status==="persisted");
  const primary=decisions.find(d=>d.state==="TAKE")||decisions[0];
  const state=actionState(item);
  const indicators=Object.entries(observation?.indicators||{}).filter(([,v])=>v!==null&&v!==undefined).slice(0,10);
  const price=observation?.underlying_price??item.scanner.underlying_price;
  const score=observation?.total_score??item.scanner.score;
  const setup=item.scanner.setup;
  const freshness=symbolFreshness(data,item);
  const liveTake=state==="TAKE"&&!stale;
  const staleTake=state==="TAKE"&&stale;
  const frame=liveTake?"border-emerald-400/40 bg-emerald-950/20":staleTake?"border-amber-400/35 bg-slate-950/50":state==="BLOCKED"?"border-dashed border-rose-300/40":state==="REJECTED"?"border-rose-400/30":state==="WAIT"?"border-dotted border-amber-300/40":state==="STALE"?"border-amber-400/35":"border-slate-800";
  return <article data-testid={`setup-${item.symbol}`} data-signal={liveTake?"live-take":staleTake?"stale-take":state.toLowerCase()} aria-label={`${item.symbol} ${state}${staleTake?" stale data":""}`} className={`surface-tight min-w-0 overflow-hidden ${frame}`}>
    <header className="flex items-start justify-between gap-3 px-3.5 py-3">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-2xl font-black tracking-tight">{item.symbol}</h2>
          <StatusBadge value={state}/>
          {staleTake?<StatusBadge value="STALE DATA"/>:null}
          <StatusBadge value={item.scanner.direction}/>
        </div>
        <p className="mt-1 text-[11px] font-semibold text-slate-300">{label(setup)} · {freshness} · {clock(observation?.observed_at??item.scanner.observed_at)}</p>
      </div>
      <div className="text-right">
        <p className="metric-label">Score</p>
        <p className={`font-mono font-black tabular-nums leading-none ${score==null?"text-lg text-slate-500":liveTake?"text-3xl text-emerald-300":"text-2xl text-slate-200"}`}>{number(score,1)}</p>
      </div>
    </header>
    <div className="grid grid-cols-2 gap-x-4 border-t border-slate-800/80 px-3.5 py-3">
      <div><p className="metric-label">Price</p><p className="metric-value text-base">{money(price)}</p></div>
      <div><p className="metric-label">Rationale</p><p className="mt-1 text-xs font-semibold text-slate-200">{label(primary?.reason_code??observation?.reason_code)}</p></div>
    </div>
    <p className="px-3.5 pb-3 text-[11px] leading-5 text-slate-500">{primary?.explanation??(observation?.explanation as string|undefined)??"No authoritative decision explanation is available."}</p>
    {indicators.length>0?<ul className="grid grid-cols-2 gap-px border-t border-slate-800 bg-slate-800/80 sm:grid-cols-4">{indicators.map(([key,v])=><li key={key} className="bg-[#0c111d] px-3.5 py-2"><p className="metric-label">{indicatorName(key)}</p><p className="font-mono text-xs text-slate-200">{number(v,3)}</p></li>)}</ul>:<p className="border-t border-slate-800 px-3.5 py-2 text-[11px] text-slate-600">Indicator values unavailable. Nothing has been reconstructed in the browser.</p>}
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
      const lifecycle=t.exit_state||t.exit_label||t.status;
      return <article key={t.id} className="px-3.5 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <strong className="text-sm">{t.symbol||"Unknown"}</strong>
          <StatusBadge value={t.direction}/>
          <StatusBadge value={lifecycle}/>
          {pnlAuthoritative?<span className={`ml-auto font-mono text-sm font-semibold tabular-nums ${outcomeTone(t.unrealized_pnl)}`}>{money(t.unrealized_pnl)}</span>:<span className="ml-auto text-[11px] text-slate-500">P&amp;L unavailable</span>}
        </div>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-4 xl:grid-cols-5">
          <div><dt className="metric-label">Entry</dt><dd className="text-xs font-semibold tabular-nums">{money(t.underlying_entry??t.entry_price)}</dd></div>
          <div><dt className="metric-label">Stop</dt><dd className="text-xs font-semibold tabular-nums">{money(t.stop)}</dd></div>
          <div><dt className="metric-label">Target</dt><dd className="text-xs font-semibold tabular-nums">{money(t.target_1)}</dd></div>
          <div><dt className="metric-label">Hold</dt><dd className="text-xs font-semibold">{t.time_in_trade_seconds==null?"Unavailable":`${Math.floor(t.time_in_trade_seconds/60)}m`}</dd></div>
          {t.breakeven_state?<div><dt className="metric-label">Breakeven</dt><dd className="text-xs font-semibold">{label(t.breakeven_state)}</dd></div>:null}
        </dl>
      </article>;
    })}</div>}
  </section>;
}

function DecisionFeed({data,stale}:{data:LiveSnapshot;stale:boolean}){
  return <section className="surface-tight overflow-hidden" aria-labelledby="decisions-heading">
    <header className="flex items-center gap-2 border-b border-slate-800 px-3.5 py-2">
      <ScanSearch size={14} className="text-violet-300" aria-hidden/>
      <h2 id="decisions-heading" className="text-sm font-semibold">Decisions</h2>
    </header>
    {data.decisions.length===0?<CompactEmpty title="No recent decisions">No recent lane decision is available.</CompactEmpty>:<ul className="divide-y divide-slate-800">{data.decisions.map((row,i)=>{
      const take=row.action==="TAKE";
      return <li key={row.decision_id??`${row.opportunity_id}:${i}`} className={`flex flex-wrap items-center gap-x-2 gap-y-1 px-3.5 py-2 text-xs ${take&&!stale?"bg-emerald-950/25":""}`}>
        <span className="w-[4.5rem] shrink-0 font-mono text-[10px] text-slate-500">{clock(row.timestamp)}</span>
        <strong className="w-8">{row.symbol}</strong>
        <span className="min-w-0 truncate text-[11px] text-slate-400">{label(row.direction)}{row.setup?` · ${label(row.setup)}`:""}</span>
        <StatusBadge value={row.action}/>
        <span className="ml-auto font-mono text-slate-300">{number(row.score,1)}</span>
        <span className="hidden min-w-0 truncate text-[11px] font-semibold text-slate-400 sm:inline">{label(row.reason_code)}</span>
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
    {trades.length===0?<CompactEmpty title="No recent trades">No completed authoritative trade is available.</CompactEmpty>:<ul className="divide-y divide-slate-800">{trades.slice(0,8).map(t=><li key={t.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3.5 py-2">
      <span className="w-[4.5rem] shrink-0 font-mono text-[10px] text-slate-600">{clock(t.closed_at??t.opened_at)}</span>
      <strong className="text-xs">{t.symbol??"Unknown"}</strong>
      <span className="min-w-0 flex-1 truncate text-[11px] text-slate-500">{label(t.direction)}<span className="hidden sm:inline"> · {money(t.entry_price)} → {money(t.exit_price)}</span> · {label(t.exit_reason??t.status)}</span>
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
    <dl className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
      <div><dt className="metric-label">Worker</dt><dd>{label(s.worker_status)}</dd></div>
      <div><dt className="metric-label">Database</dt><dd>{label(s.database)}</dd></div>
      <div><dt className="metric-label">SPY coverage</dt><dd>{coverageLabel(data.system.coverage.SPY)}</dd></div>
      <div><dt className="metric-label">QQQ coverage</dt><dd>{coverageLabel(data.system.coverage.QQQ)}</dd></div>
      <div><dt className="metric-label">Provenance</dt><dd>{lc(data.provenance.data_status)==="persisted"?"Ready":"Not ready"}</dd></div>
    </dl>
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
  const stale=isAuthoritativeStale(data);
  const disconnected=Boolean(snapshot.error);
  return <div className="mx-auto max-w-[1680px] overflow-x-hidden px-3 py-4 sm:px-5 lg:px-6">
    <TerminalHeader data={data} disconnected={disconnected} refreshing={snapshot.isValidating} refresh={()=>snapshot.mutate()}/>
    <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-2"><SetupCard item={data.symbols.SPY} stale={stale} data={data}/><SetupCard item={data.symbols.QQQ} stale={stale} data={data}/></div>
    <div className="mt-3 min-w-0"><Positions trades={data.active_trades}/></div>
    <div className="mt-3 grid min-w-0 items-start gap-3 xl:grid-cols-2"><DecisionFeed data={data} stale={stale}/><RecentTrades trades={data.recent_trades}/></div>
    <div className="mt-3"><Health data={data}/></div>
    <footer className="mt-3 flex items-center gap-2 text-[10px] text-slate-600"><Database size={12} aria-hidden/>Presentation only. No provider calls, strategy evaluation, or trading actions occur in this interface.</footer>
  </div>;
}
