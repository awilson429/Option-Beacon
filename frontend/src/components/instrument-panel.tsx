"use client";

import { Activity, Beaker, Crosshair, ShieldCheck } from "lucide-react";
import type { SWRResponse } from "swr";
import { EmptyState, SectionError } from "./empty-state";
import { InstrumentSkeleton } from "./instrument-skeleton";
import { Metric } from "./metric";
import { ScalpLifecycle } from "./scalp-lifecycle";
import { StatusBadge } from "./status-badge";
import { compact, label, money, number, percent, timestamp } from "@/lib/format";
import type { PerformanceResponse, ScalpState, StrategyState, SymbolCode } from "@/lib/types";

interface Props {
  symbol: SymbolCode;
  strategy: SWRResponse<StrategyState>;
  scalp: SWRResponse<ScalpState>;
  performance: SWRResponse<PerformanceResponse>;
}

function TradePlan({ data }: { data: StrategyState }) {
  const setup = data.setup;
  const zone = setup.entry_zone;
  const trigger = data.trade_coverage.entry_trigger;
  const hasPlan = Boolean(zone || trigger != null || setup.stop != null || setup.targets?.length);
  return <section aria-labelledby={`${data.symbol}-plan`}>
    <div className="mb-3 flex items-center gap-2"><Crosshair aria-hidden size={14} className="text-violet-300"/><h3 id={`${data.symbol}-plan`} className="eyebrow">Trade plan</h3></div>
    {!hasPlan ? <EmptyState title="Setup developing">Entry zone, stop, targets, and chase level will appear when supplied by OptionBeacon.</EmptyState> :
      <div className="grid grid-cols-2 gap-x-4 gap-y-5 rounded-lg border border-slate-800 bg-slate-950/25 p-4 sm:grid-cols-3">
        <Metric label="Entry" value={zone ? `${money(zone[0])} – ${money(zone[1])}` : "Awaiting zone"}/>
        <Metric label="Trigger" value={money(trigger)}/><Metric label="Max chase" value={money(setup.maximum_chase)}/>
        <Metric label="Stop" value={money(setup.stop)} accent="text-rose-300"/>
        <Metric label="Targets" value={setup.targets?.length ? setup.targets.map(v=>money(v)).join(" · ") : "Unavailable"} accent="text-emerald-300"/>
        <Metric label="Risk / reward" value={number(setup.risk_reward)}/>
      </div>}
  </section>;
}

function ContractCard({ data }: { data: StrategyState }) {
  const contract = data.setup;
  return <section aria-labelledby={`${data.symbol}-contract`}>
    <div className="mb-3 flex items-center gap-2"><ShieldCheck aria-hidden size={14} className="text-violet-300"/><h3 id={`${data.symbol}-contract`} className="eyebrow">Recommended contract</h3></div>
    {!contract.contract ? <EmptyState title="Awaiting contract">OptionBeacon will select a contract when the current setup reaches the required state.</EmptyState> :
      <div className="rounded-lg border border-violet-400/20 bg-violet-400/[.045] p-4">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-mono text-base font-bold tracking-tight text-white">{contract.contract}</p><p className="mt-1 text-xs text-slate-500">{contract.expiration || "Expiration unavailable"} · {contract.dte == null ? "DTE unavailable" : `${contract.dte}DTE`}</p></div><StatusBadge value={data.bias.direction}/></div>
        <div className="mt-5 grid grid-cols-3 gap-x-3 gap-y-5"><Metric label="Strike" value={money(contract.strike)}/><Metric label="Bid" value={money(contract.bid)}/><Metric label="Ask" value={money(contract.ask)}/><Metric label="Spread" value={percent(contract.spread)}/><Metric label="Delta" value={number(contract.delta)}/><Metric label="Volume / OI" value={`${compact(contract.volume)} / ${compact(contract.open_interest)}`}/></div>
      </div>}
  </section>;
}

function StrategyContent({ data }: { data: StrategyState }) {
  const bias = data.bias.direction;
  return <>
    <header className="border-b border-slate-800/80 px-5 py-5">
      <div className="flex items-start justify-between gap-4">
        <div><div className="flex items-center gap-3"><h2 className="text-lg font-black tracking-[.08em]">{data.symbol}</h2><StatusBadge dot value={data.market_status === "open" ? "LIVE" : data.market_status}/></div><p className="mt-2 text-3xl font-semibold tracking-[-.045em] tabular-nums">{money(data.price)}</p></div>
        <div className="flex flex-col items-end gap-2"><StatusBadge value={bias}/><StatusBadge value={data.trade_coverage.state || data.setup.state}/></div>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-2"><StatusBadge value={data.market_condition.regime}/>{data.setup.score != null && <span className="text-xs font-semibold text-slate-300">Score {number(data.setup.score,0)}</span>}<span className="ml-auto text-[10px] text-slate-600">{timestamp(data.last_updated)}</span></div>
    </header>
    <div className="grid gap-6 p-5 lg:grid-cols-2"><TradePlan data={data}/><ContractCard data={data}/></div>
    <div className="grid border-t border-slate-800/80 px-5 py-4 sm:grid-cols-2">
      <div><p className="metric-label">Context coverage</p><p className="mt-1 text-xs font-semibold text-slate-300">{label(data.context.level)}</p><div className="mt-2 flex flex-wrap gap-1.5">{data.context.known_factors.length ? data.context.known_factors.map(item=><span key={item} className="rounded bg-slate-800/70 px-2 py-1 text-[9px] font-semibold uppercase text-slate-400">{label(item)}</span>) : <span className="text-xs text-slate-600">No context factors supplied</span>}</div></div>
      <div className="mt-4 border-t border-slate-800/70 pt-4 sm:mt-0 sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0"><p className="metric-label">Confirmations</p><p className="mt-1 text-xs font-semibold text-slate-300">{label(data.confirmations.state)}</p><p className="mt-2 text-xs text-slate-600">{data.confirmations.items.length ? data.confirmations.items.map(label).join(" · ") : "No confirmation detail supplied"}</p></div>
    </div>
  </>;
}

function ScalpResearch({ scalp, performance, symbol }: Pick<Props,"scalp"|"performance"|"symbol">) {
  const current=scalp.data?.current; const metrics=performance.data?.metrics; const evidence=(metrics?.evidence || "INSUFFICIENT").toUpperCase();
  return <section className="border-t border-cyan-400/15 bg-cyan-400/[.018] px-5 py-5" aria-labelledby={`${symbol}-scalp`}>
    <div className="flex flex-wrap items-center gap-2"><Beaker aria-hidden size={15} className="text-cyan-300"/><h3 id={`${symbol}-scalp`} className="eyebrow !text-cyan-200">Scalp research</h3><StatusBadge value="SHADOW"/><span className="ml-auto text-[10px] text-slate-600">Simulation only</span></div>
    <p className="mt-2 text-[11px] leading-5 text-slate-500">Research simulation only. Does not affect live OptionBeacon recommendations.</p>
    {scalp.error ? <div className="mt-4"><SectionError label={`${symbol} scalp state`} retry={()=>scalp.mutate()}/></div> : !scalp.data ? <div className="skeleton mt-4 h-24"/> :
      <div className="mt-4"><ScalpLifecycle current={current?.state}/>{!current ? <div className="mt-4"><EmptyState title="No active research setup">The shadow engine has no persisted {symbol} opportunity right now.</EmptyState></div> : <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4"><Metric label="Direction" value={label(current.direction)}/><Metric label="Setup" value={label(current.setup_family)}/><Metric label="Trigger" value={money(current.entry_trigger)}/><Metric label="Invalidation" value={money(current.invalidation)}/><Metric label="Max chase" value={money(current.maximum_chase)}/><Metric label="Probability" value={current.probability == null ? "Unavailable" : percent(current.probability*100)}/><Metric label="Expected hold" value={current.expected_hold_minutes ? `${current.expected_hold_minutes[0]}–${current.expected_hold_minutes[1]}m` : "Unavailable"}/><Metric label="Expected move" value={money(current.expected_move)}/></div>}</div>}
    <div className="mt-5 border-t border-slate-800/80 pt-5">
      {performance.error ? <SectionError label={`${symbol} research performance`} retry={()=>performance.mutate()}/> : !performance.data ? <div className="skeleton h-20"/> : <><div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2"><Activity aria-hidden size={14} className="text-slate-500"/><p className="eyebrow">Shadow performance</p></div><span className={`text-[10px] font-bold tracking-[.12em] ${evidence.includes("INSUFFICIENT") ? "text-amber-300" : "text-slate-300"}`}>{evidence.includes("INSUFFICIENT") ? "INSUFFICIENT EVIDENCE" : evidence}</span></div><div className="grid grid-cols-2 gap-4 sm:grid-cols-4"><Metric label="Trades" value={number(metrics?.triggered_trades,0)}/><Metric label="Win rate" value={percent(metrics?.win_rate)}/><Metric label="Expectancy" value={money(metrics?.expectancy)}/><Metric label="Profit factor" value={number(metrics?.profit_factor)}/><Metric label="Net sim P&L" value={money(metrics?.net_simulated_pnl)}/><Metric label="Max drawdown" value={money(metrics?.maximum_drawdown)}/><Metric label="Avg hold" value={metrics?.average_hold_minutes == null ? "Unavailable" : `${number(metrics.average_hold_minutes,1)}m`}/><Metric label="Evidence" value={label(metrics?.evidence)}/></div></>}
    </div>
  </section>;
}

export function InstrumentPanel({ symbol, strategy, scalp, performance }: Props) {
  if (!strategy.data && !strategy.error) return <InstrumentSkeleton/>;
  return <article data-testid={`instrument-${symbol}`} className="surface overflow-hidden">
    {strategy.error ? (
      <div className="p-5"><div className="mb-4 flex items-center gap-2"><h2 className="text-lg font-black">{symbol}</h2><StatusBadge value="STALE"/></div><SectionError label={`${symbol} strategy`} retry={()=>strategy.mutate()}/></div>
    ) : strategy.data ? <StrategyContent data={strategy.data}/> : null}
    <ScalpResearch symbol={symbol} scalp={scalp} performance={performance}/>
  </article>;
}
