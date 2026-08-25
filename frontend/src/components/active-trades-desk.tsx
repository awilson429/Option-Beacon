"use client";

import { Activity, Clock3, Database, Gauge, RefreshCw, ShieldCheck, Target, TrendingUp } from "lucide-react";
import { useActiveTrades, useSystemStatus } from "@/hooks/use-options-data";
import { label, money, number, percent, timestamp } from "@/lib/format";
import type { ActiveTrade } from "@/lib/types";
import { EmptyState, SectionError } from "./empty-state";
import { Metric } from "./metric";
import { StatusBadge } from "./status-badge";

function duration(seconds:number|null) {
  if(seconds==null) return "Unavailable";
  const minutes=Math.floor(seconds/60); const remainder=seconds%60;
  if(minutes<60) return `${minutes}m ${remainder}s`;
  const hours=Math.floor(minutes/60); return `${hours}h ${minutes%60}m`;
}

function sumKnown(trades:ActiveTrade[], field:"capital_committed"|"initial_dollar_risk"|"unrealized_pnl") {
  const values=trades.map(trade=>trade[field]).filter((value):value is number=>value!=null);
  return values.length?values.reduce((total,value)=>total+value,0):null;
}

function planValues(trade:ActiveTrade) {
  return [trade.stop,trade.underlying_entry,trade.latest_underlying,trade.target_1,trade.target_2,trade.target_3]
    .filter((value):value is number=>value!=null);
}

function Progress({ trade }:{trade:ActiveTrade}) {
  const values=planValues(trade); const current=trade.latest_underlying;
  if(values.length<3||current==null) return <p className="mt-4 text-[10px] text-slate-600">Progress unavailable · underlying plan values are incomplete.</p>;
  const low=Math.min(...values); const high=Math.max(...values);
  if(high===low) return null;
  const place=(value:number)=>Math.min(100,Math.max(0,((value-low)/(high-low))*100));
  const markers=[{name:"Stop",value:trade.stop,tone:"bg-rose-400"},{name:"Entry",value:trade.underlying_entry,tone:"bg-slate-400"},{name:"T1",value:trade.target_1,tone:"bg-violet-300"},{name:"T2",value:trade.target_2,tone:"bg-violet-400"},{name:"T3",value:trade.target_3,tone:"bg-violet-500"}].filter(item=>item.value!=null);
  return <div className="mt-5" aria-label="Trade plan progress"><div className="flex items-center justify-between"><p className="metric-label">Underlying plan progress</p><p className="font-mono text-[10px] text-slate-500">{money(low)} — {money(high)}</p></div><div className="relative mt-4 h-2 rounded-full bg-slate-800"><div className="absolute inset-y-0 left-0 rounded-full bg-violet-500/20" style={{width:`${place(current)}%`}}/><span className="absolute top-1/2 z-10 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#0c111d] bg-emerald-300 shadow-[0_0_12px_rgba(110,231,183,.5)]" style={{left:`${place(current)}%`}} title={`Current ${money(current)}`}/>{markers.map(item=><span key={item.name} className={`absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full ${item.tone}`} style={{left:`${place(item.value!)}%`}} title={`${item.name} ${money(item.value)}`}/>)}</div><div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[9px] uppercase tracking-wider text-slate-600"><span className="text-emerald-300">Current {money(current)}</span>{markers.map(item=><span key={item.name}>{item.name} {money(item.value)}</span>)}</div></div>;
}

function Plan({ trade }:{trade:ActiveTrade}) {
  const values=[["Stop",trade.stop],["Target 1",trade.target_1],["Target 2",trade.target_2],["Target 3",trade.target_3]] as const;
  return <section className="rounded-lg border border-slate-800 bg-slate-950/25 p-4" aria-label="Position plan"><div className="flex items-center gap-2"><Target aria-hidden size={13} className="text-violet-300"/><p className="eyebrow">Plan</p></div><div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">{values.map(([name,value])=><Metric key={name} label={name} value={money(value)}/>)}</div><Progress trade={trade}/></section>;
}

function Management({ trade }:{trade:ActiveTrade}) {
  const states=[trade.trade_coach_status,trade.thesis_status,trade.momentum_state,trade.structure_state,trade.target_progress,trade.stop_management_state].filter((value):value is string=>Boolean(value));
  return <section className={`rounded-lg border p-4 ${trade.management_data_status==="persisted"?"border-violet-400/20 bg-violet-400/[.035]":"border-slate-800 bg-slate-950/25"}`} aria-label="Trade management"><div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-center gap-2"><Gauge aria-hidden size={13} className="text-violet-300"/><div><p className="eyebrow">Trade management</p><p className="mt-1 text-xs font-semibold text-slate-200">{trade.exit_state?label(trade.exit_state):"Management state unavailable"}</p></div></div>{trade.exit_score!=null?<div className="text-right"><p className="metric-label">Exit score</p><p className="mt-1 font-mono text-2xl font-semibold text-violet-200">{trade.exit_score}</p></div>:<StatusBadge value="UNAVAILABLE"/>}</div>{states.length?<div className="mt-4 flex flex-wrap gap-2">{states.map(state=><StatusBadge key={state} value={state}/>)}</div>:<p className="mt-4 text-[10px] leading-4 text-slate-600">No canonically attributable Trade Coach or Exit Score snapshot is persisted for this position.</p>}{trade.last_management_update&&<p className="mt-3 text-[9px] uppercase tracking-wider text-slate-600">Last management update {timestamp(trade.last_management_update)}</p>}</section>;
}

function PositionCard({ trade }:{trade:ActiveTrade}) {
  const pnl=trade.unrealized_pnl; const markMissing=trade.latest_option_mark==null;
  return <article data-testid={`active-trade-${trade.id}`} className="surface overflow-hidden"><header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 px-5 py-4"><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold tracking-tight">{trade.symbol||"Unknown"} {trade.strike!=null?number(trade.strike,2):""} {label(trade.option_type||trade.direction)}</h2><StatusBadge value={trade.lane}/><StatusBadge value={trade.status}/></div><p className="mt-2 break-all font-mono text-[10px] text-slate-500">{trade.contract_symbol||"Contract identity unavailable"}</p></div><div className="text-right"><p className="text-[10px] font-bold uppercase tracking-[.14em] text-slate-400">{trade.lane==="OB"?"Authoritative lane":"Paper lane"}</p><p className="mt-1 text-[10px] text-slate-600">{trade.quantity!=null?`${trade.quantity} contract${trade.quantity===1?"":"s"}`:"Quantity unavailable"} · {trade.dte!=null?`${trade.dte}DTE`:"DTE unavailable"}</p></div></header><div className="p-5"><div className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 xl:grid-cols-6"><Metric label="Option entry" value={money(trade.option_entry_premium)}/><Metric label="Current mark" value={markMissing?"Price unavailable":money(trade.latest_option_mark)}/><Metric label="Unrealized P&L" value={money(pnl)} accent={pnl==null?undefined:pnl>=0?"text-emerald-300":"text-rose-300"}/><Metric label="Return" value={percent(trade.unrealized_return_pct)} accent={(trade.unrealized_return_pct||0)>=0?"text-emerald-300":"text-rose-300"}/><Metric label="Time in trade" value={duration(trade.time_in_trade_seconds)}/><Metric label="Last mark" value={trade.mark_timestamp?timestamp(trade.mark_timestamp):"No mark recorded"}/></div>{(trade.data_freshness!=="fresh"||markMissing)&&<div role="status" className={`mt-4 rounded-md border px-3 py-2 text-[10px] ${trade.data_freshness==="stale"?"border-amber-400/20 bg-amber-400/[.05] text-amber-200":"border-slate-700 bg-slate-950/20 text-slate-500"}`}>{trade.data_freshness==="stale"?"Mark stale · position details remain visible while persisted pricing awaits an update.":"Price unavailable · risk and plan values remain isolated from missing mark data."}</div>}<div className="mt-5 grid gap-4 2xl:grid-cols-[1.35fr_.9fr]"><Plan trade={trade}/><Management trade={trade}/></div><section className="mt-4 rounded-lg border border-slate-800 bg-slate-950/25 p-4" aria-label="Position risk"><div className="flex items-center gap-2"><ShieldCheck aria-hidden size={13} className="text-violet-300"/><p className="eyebrow">Risk & allocation</p></div><div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4"><Metric label="Capital committed" value={money(trade.capital_committed)}/><Metric label="Initial risk" value={money(trade.initial_dollar_risk)}/><Metric label="Current risk" value={money(trade.current_dollar_risk)}/><Metric label="Lane account risk" value={percent(trade.account_risk_pct)}/></div></section></div></article>;
}

function LoadingCards() {
  return <div aria-label="Loading active trades" className="grid gap-5 xl:grid-cols-2">{[1,2].map(item=><div key={item} className="surface p-5"><div className="flex justify-between"><div className="skeleton h-6 w-44"/><div className="skeleton h-6 w-20"/></div><div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3">{Array.from({length:6}).map((_,index)=><div key={index} className="skeleton h-12"/>)}</div><div className="mt-5 skeleton h-36"/></div>)}</div>;
}

export function ActiveTradesDesk() {
  const active=useActiveTrades(); const system=useSystemStatus(); const trades=active.data||[];
  const refresh=()=>Promise.all([active.mutate(),system.mutate()]);
  const freshness=trades.some(trade=>trade.data_freshness==="stale")?"STALE":trades.some(trade=>trade.data_freshness==="fresh")?"FRESH":"UNAVAILABLE";
  const lastMark=trades.map(trade=>trade.mark_timestamp).filter((value):value is string=>Boolean(value)).sort().at(-1)||null;
  return <div className="mx-auto max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8"><header className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow text-violet-300">OptionBeacon / Active Trades</p><h1 className="mt-2 text-2xl font-semibold tracking-[-.035em] sm:text-3xl">Active Trades</h1><p className="mt-2 max-w-2xl text-xs leading-5 text-slate-500">Read-only operational state for current OB and BROAD positions. Execution and management remain authoritative in Python.</p></div><button onClick={refresh} className="flex shrink-0 items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-[10px] font-bold uppercase tracking-[.11em] text-slate-300 hover:border-slate-500"><RefreshCw aria-hidden size={13}/>Refresh</button></header><section className="surface mt-6 overflow-hidden" aria-labelledby="active-summary"><header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-4"><div className="flex items-center gap-2"><Activity aria-hidden size={15} className="text-violet-300"/><div><p className="eyebrow">Live persisted exposure</p><h2 id="active-summary" className="mt-1 text-base font-semibold">Open-position summary</h2></div></div><div className="flex flex-wrap gap-2"><StatusBadge value={system.data?.market_status}/><StatusBadge value={freshness}/></div></header><div className="grid grid-cols-2 gap-x-4 gap-y-6 p-5 sm:grid-cols-3 xl:grid-cols-7"><Metric label="Open positions" value={active.data?number(trades.length,0):"Loading"}/><Metric label="Capital committed" value={money(sumKnown(trades,"capital_committed"))}/><Metric label="Open risk" value={money(sumKnown(trades,"initial_dollar_risk"))}/><Metric label="Unrealized P&L" value={money(sumKnown(trades,"unrealized_pnl"))} accent={(sumKnown(trades,"unrealized_pnl")||0)>=0?"text-emerald-300":"text-rose-300"}/><Metric label="Market" value={label(system.data?.market_status)}/><Metric label="Data freshness" value={label(freshness)}/><Metric label="Last update" value={lastMark?timestamp(lastMark):"No mark recorded"}/></div></section><div className="mt-5">{active.error?<SectionError label="Active trades" retry={()=>active.mutate()}/>:!active.data?<LoadingCards/>:trades.length===0?<EmptyState title="No active trades">OptionBeacon is monitoring the market for qualified opportunities.</EmptyState>:<div className="grid items-start gap-5 xl:grid-cols-2">{trades.map(trade=><PositionCard key={trade.id} trade={trade}/>)}</div>}</div><footer className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-[10px] text-slate-700"><span className="flex items-center gap-2"><Database aria-hidden size={12}/>Persisted, read-only state · no provider calls or trade controls</span><span className="flex items-center gap-2"><Clock3 aria-hidden size={12}/>Positions refresh every 5s · system status every 15s</span><span className="flex items-center gap-2"><TrendingUp aria-hidden size={12}/>MIRROR remains research/control and is excluded here</span></footer></div>;
}
