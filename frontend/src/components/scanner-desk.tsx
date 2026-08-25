"use client";

import { Activity, Clock3, Database, HeartPulse, Radar, RefreshCw, ShieldCheck, Waves } from "lucide-react";
import { useScannerData } from "@/hooks/use-options-data";
import { label, money, number, percent, timestamp } from "@/lib/format";
import type { ScannerInstrument, ScannerLaneDecision, ScannerOpportunity, ScannerResponse } from "@/lib/types";
import { EmptyState, SectionError } from "./empty-state";
import { Metric } from "./metric";
import { StatusBadge } from "./status-badge";

function section(data: ScannerResponse, name: string) {
  return data.sections.find(item=>item.section===name);
}

function age(value: number|null) {
  if(value==null) return "Unavailable";
  if(value<60) return `${value}s`;
  if(value<3600) return `${Math.floor(value/60)}m`;
  return `${Math.floor(value/3600)}h ${Math.floor((value%3600)/60)}m`;
}

function compactTimestamp(value: string|null) {
  return timestamp(value).replace(/:\d{2} /," ");
}

function contextValues(context: Record<string,unknown>) {
  return Object.entries(context).filter(([,value])=>["string","number","boolean"].includes(typeof value)).slice(0,3);
}

function ScannerLoading() {
  return <div aria-label="Loading scanner" className="space-y-5">
    <section className="surface p-5"><div className="skeleton h-5 w-44"/><div className="mt-5 grid grid-cols-2 gap-4 lg:grid-cols-4">{[1,2,3,4].map(i=><div key={i} className="skeleton h-12"/>)}</div></section>
    <div className="grid gap-5 xl:grid-cols-2">{[1,2].map(i=><div key={i} className="surface p-5"><div className="skeleton h-6 w-32"/><div className="mt-5 skeleton h-40"/></div>)}</div>
    <section className="surface p-5"><div className="skeleton h-5 w-52"/><div className="mt-5 skeleton h-44"/></section>
  </div>;
}

function HealthSummary({ data }: { data:ScannerResponse }) {
  const health=data.health;
  return <section className="surface overflow-hidden" aria-labelledby="scanner-health-heading">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-4">
      <div className="flex items-center gap-2"><Radar aria-hidden size={15} className="text-violet-300"/><div><p className="eyebrow">Scanner status</p><h2 id="scanner-health-heading" className="mt-1 text-base font-semibold">Persisted worker heartbeat</h2></div></div>
      <div className="flex flex-wrap gap-2"><StatusBadge value={health.state}/><StatusBadge value={health.market_data_state}/><StatusBadge value={health.data_freshness}/></div>
    </header>
    <div className="grid grid-cols-2 gap-x-4 gap-y-6 p-5 sm:grid-cols-3 xl:grid-cols-6">
      <Metric label="Worker" value={label(health.worker_status)}/><Metric label="Last success" value={compactTimestamp(health.last_success_at)}/>
      <Metric label="Last cycle" value={health.scan_duration_seconds==null?"Unavailable":`${number(health.scan_duration_seconds,1)}s`}/>
      <Metric label="Processed" value={health.symbols_processed==null?"Unavailable":number(health.symbols_processed,0)}/>
      <Metric label="Failures" value={health.failures==null?"Unavailable":number(health.failures,0)}/>
      <Metric label="Next expected" value={health.next_expected_at?compactTimestamp(health.next_expected_at):"Unavailable"}/>
    </div>
    <p className="border-t border-slate-800/70 px-5 py-3 text-[10px] leading-4 text-slate-500">{health.message} Provider state is not queried from the React request path.</p>
  </section>;
}

function InstrumentCard({ item, retry }: { item:ScannerInstrument; retry:()=>void }) {
  const context=contextValues(item.context);
  return <article data-testid={`scanner-${item.symbol}`} className="surface min-w-0 overflow-hidden">
    <header className="flex items-start justify-between gap-3 border-b border-slate-800 px-5 py-4">
      <div><p className="eyebrow">Index scan</p><div className="mt-1 flex flex-wrap items-center gap-2"><h2 className="text-xl font-black tracking-[.08em]">{item.symbol}</h2><StatusBadge value={item.direction}/><StatusBadge value={item.signal_state}/></div></div>
      <StatusBadge dot value={item.freshness}/>
    </header>
    <div className="p-5">{item.data_status==="error"?<SectionError label={`${item.symbol} scanner state`} retry={retry}/>:item.data_status!=="persisted"?<EmptyState title="No qualifying setup right now">No canonical {item.symbol} opportunity is persisted. The scanner may still be monitoring a non-eligible setup.</EmptyState>:<>
      <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3">
        <Metric label="Last persisted underlying" value={money(item.underlying_price)}/><Metric label="Setup" value={label(item.setup)}/>
        <Metric label="Confidence" value={item.confidence==null?"Unavailable":percent(item.confidence)}/><Metric label="Rule score" value={item.score==null?"Unavailable":number(item.score,0)}/>
        <Metric label="Signal age" value={age(item.signal_age_seconds)}/><Metric label="Actionable" value={item.actionable?"Yes":"No"} accent={item.actionable?"text-emerald-300":"text-slate-400"}/>
      </div>
      {context.length>0&&<div className="mt-5 flex flex-wrap gap-2 border-t border-slate-800/70 pt-4">{context.map(([key,value])=><span key={key} className="rounded-md border border-slate-800 bg-slate-950/30 px-2.5 py-1.5 text-[10px] text-slate-400"><strong className="font-semibold text-slate-300">{label(key)}:</strong> {String(value)}</span>)}</div>}
      <p className="mt-4 text-[10px] text-slate-600">Observed {compactTimestamp(item.observed_at)} · persisted eligible lifecycle only</p>
    </>}</div>
  </article>;
}

function LaneDecision({ decision }: { decision:ScannerLaneDecision }) {
  return <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-950/30 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-xs tracking-[.12em]">{decision.lane}</strong><StatusBadge value={decision.state}/></div>
    {decision.data_status!=="persisted"?<p className="mt-4 text-xs leading-5 text-slate-600">No canonical lane decision is persisted for this opportunity.</p>:<>
      <p className="mt-4 text-[10px] font-bold uppercase tracking-[.1em] text-slate-500">{label(decision.reason_code)}</p>
      <p className="mt-1 text-xs leading-5 text-slate-400">{decision.explanation||"No explanation persisted."}</p>
      <div className="mt-4 grid grid-cols-2 gap-4"><Metric label="Contract" value={<span className="break-all">{decision.proposed_contract||"Unavailable"}</span>}/><Metric label="Planned risk" value={decision.proposed_quantity?money(decision.proposed_dollar_risk):"—"}/></div>
    </>}
  </div>;
}

function OpportunityCard({ item }: { item:ScannerOpportunity }) {
  return <article className="rounded-xl border border-slate-800 bg-slate-950/25 p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><div className="flex flex-wrap items-center gap-2"><strong className="text-base tracking-wide">{item.symbol}</strong><StatusBadge value={item.direction}/><StatusBadge value={item.status}/><StatusBadge value={item.freshness}/></div><p className="mt-2 text-xs text-slate-500">{label(item.strategy)} · {compactTimestamp(item.observed_at)}</p></div>
      <p className="max-w-full break-all font-mono text-[10px] text-slate-600">{item.contract||"Contract unavailable"}</p>
    </div>
    <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
      <Metric label="Entry" value={money(item.entry)}/><Metric label="Stop" value={money(item.stop)}/><Metric label="Target 1" value={money(item.targets[0])}/>
      <Metric label="Target 2" value={money(item.targets[1])}/><Metric label="Confidence" value={item.confidence==null?"Unavailable":percent(item.confidence)}/><Metric label="Rule score" value={item.score==null?"Unavailable":number(item.score,0)}/>
    </div>
    <div className="mt-5 grid gap-3 lg:grid-cols-2">{item.lane_decisions.map(decision=><LaneDecision key={decision.lane} decision={decision}/>)}</div>
  </article>;
}

function Opportunities({ data, retry }: { data:ScannerResponse; retry:()=>void }) {
  const status=section(data,"opportunities"); const laneStatus=section(data,"lane_decisions");
  const current=data.opportunities.filter(item=>item.actionable);
  return <section className="surface overflow-hidden" aria-labelledby="opportunities-heading">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-4"><div className="flex items-center gap-2"><ShieldCheck aria-hidden size={15} className="text-violet-300"/><div><p className="eyebrow">Current opportunities</p><h2 id="opportunities-heading" className="mt-1 text-base font-semibold">Actionable persisted setups · OB / BROAD</h2></div></div><StatusBadge value={current.length?"LIVE":"WATCHING"}/></header>
    <div className="p-5">{status?.data_status==="error"?<SectionError label="Scanner opportunities" retry={retry}/>:<>
      {laneStatus?.data_status==="error"&&<div className="mb-4"><SectionError label="OB/BROAD decisions" retry={retry}/></div>}
      {current.length===0?<EmptyState title="No qualifying setup right now">OptionBeacon has no current persisted SPY or QQQ opportunity. Inactivity is an intentional scanner state.</EmptyState>:<div className="space-y-3">{current.map(item=><OpportunityCard key={item.opportunity_id} item={item}/>)}</div>}
      <div className="mt-4 flex items-start gap-2 rounded-lg border border-cyan-400/10 bg-cyan-400/[.025] px-4 py-3 text-[10px] leading-4 text-slate-500"><Waves aria-hidden size={13} className="mt-0.5 shrink-0 text-cyan-300"/><span><strong className="text-cyan-200">MIRROR / CONTROL RESEARCH</strong> remains research-only and is not a capital lane. Only OB and BROAD decisions appear above.</span></div>
    </>}</div>
  </section>;
}

function RecentActivity({ data, retry }: { data:ScannerResponse; retry:()=>void }) {
  const status=section(data,"recent_activity");
  if(status?.data_status==="error") return <section className="surface p-5"><SectionError label="Recent scanner activity" retry={retry}/></section>;
  return <section className="surface overflow-hidden" aria-labelledby="scanner-activity-heading">
    <header className="flex items-center gap-2 border-b border-slate-800 px-5 py-4"><Activity aria-hidden size={15} className="text-violet-300"/><div><p className="eyebrow">Recent scanner activity</p><h2 id="scanner-activity-heading" className="mt-1 text-base font-semibold">What was seen, accepted, or rejected</h2></div></header>
    <div className="p-5">{status?.data_status==="partial"&&<div role="status" className="mb-4 rounded-lg border border-amber-400/20 bg-amber-400/[.06] p-3 text-xs text-amber-100">{status.message}</div>}{data.recent_activity.length===0?<EmptyState title="No recent scanner activity">No canonical opportunity, lane decision, or trade event has been persisted yet.</EmptyState>:<div className="divide-y divide-slate-800/70">{data.recent_activity.map(item=><article key={item.activity_id} className="grid gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[92px_minmax(0,1fr)_auto] sm:items-center sm:gap-4"><time className="font-mono text-[10px] text-slate-600">{compactTimestamp(item.occurred_at)}</time><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><strong className="text-xs">{item.lane?`${item.lane} · `:""}{item.symbol||"System"}</strong>{item.direction&&<StatusBadge value={item.direction}/>}<span className="text-[9px] font-semibold uppercase tracking-[.12em] text-slate-600">{label(item.event_type)}</span></div><p className="mt-1 text-xs leading-5 text-slate-500">{item.description}</p>{item.reason_code&&<p className="mt-1 text-[9px] font-bold uppercase tracking-[.12em] text-slate-600">{label(item.reason_code)}</p>}</div><div className="sm:text-right"><StatusBadge value={item.status}/></div></article>)}</div>}</div>
  </section>;
}

function SystemHealth({ data }: { data:ScannerResponse }) {
  return <section className="surface overflow-hidden" aria-labelledby="scanner-system-heading"><header className="flex items-center gap-2 border-b border-slate-800 px-5 py-4"><HeartPulse aria-hidden size={15} className="text-violet-300"/><div><p className="eyebrow">System / data health</p><h2 id="scanner-system-heading" className="mt-1 text-base font-semibold">Compact operational read</h2></div></header><div className="grid grid-cols-2 gap-5 p-5 sm:grid-cols-3"><Metric label="Market" value={label(data.market_status)}/><Metric label="Worker" value={label(data.health.worker_status)}/><Metric label="Market data" value={label(data.health.market_data_state)}/><Metric label="Freshness" value={label(data.health.data_freshness)}/><Metric label="Provider" value={label(data.health.provider_status)}/><Metric label="API read" value={label(data.data_status)}/></div></section>;
}

export function ScannerDesk() {
  const response=useScannerData();
  const refresh=()=>response.mutate();
  return <div className="mx-auto max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
    <div className="mb-6 flex items-end justify-between gap-4"><div><p className="eyebrow text-violet-300">Trade / Scanner</p><h1 className="mt-2 text-2xl font-semibold tracking-[-.035em] sm:text-3xl">Scanner</h1><p className="mt-2 max-w-2xl text-xs leading-5 text-slate-500">A persisted operational view of what OptionBeacon is seeing in SPY and QQQ, with independent OB/BROAD capital decisions.</p></div><button onClick={refresh} className="flex shrink-0 items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-[10px] font-bold uppercase tracking-[.11em] text-slate-300 hover:border-slate-500"><RefreshCw aria-hidden size={13}/>Refresh</button></div>
    {response.error?<section className="surface p-5"><SectionError label="Scanner" retry={refresh}/></section>:!response.data?<ScannerLoading/>:<>
      {response.data.health.data_freshness==="stale"&&<div role="alert" className="mb-5 flex items-start gap-3 rounded-xl border border-amber-400/25 bg-amber-400/[.07] px-4 py-3 text-xs leading-5 text-amber-100"><Clock3 aria-hidden size={16} className="mt-0.5 shrink-0"/><span><strong>Stale scanner data.</strong> Review the last-success time before acting on any persisted setup.</span></div>}
      <HealthSummary data={response.data}/>
      <section className="mt-5" aria-labelledby="instrument-scans-heading"><div className="mb-3"><p className="eyebrow">SPY / QQQ scan</p><h2 id="instrument-scans-heading" className="mt-1 text-base font-semibold">What is OptionBeacon seeing right now?</h2></div><div className="grid items-start gap-5 xl:grid-cols-2">{response.data.instruments.map(item=><InstrumentCard key={item.symbol} item={item} retry={refresh}/>)}</div></section>
      <div className="mt-5"><Opportunities data={response.data} retry={refresh}/></div>
      <div className="mt-5 grid items-start gap-5 xl:grid-cols-[1.5fr_.7fr]"><RecentActivity data={response.data} retry={refresh}/><SystemHealth data={response.data}/></div>
    </>}
    <footer className="mt-5 flex items-start gap-2 text-[10px] leading-4 text-slate-700"><Database aria-hidden size={12} className="mt-0.5 shrink-0"/>Read-only persisted state. Scanner execution, strategy logic, provider calls, and capital simulation remain in Python workers.</footer>
  </div>;
}
