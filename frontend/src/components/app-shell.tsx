"use client";

import { Activity, Bell, BookOpen, ChartNoAxesCombined, ChevronRight, CircleGauge, FileChartColumn, HeartPulse, Menu, ScanSearch, Settings, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { StatusBadge } from "./status-badge";
import { timestamp } from "@/lib/format";
import { useSystemStatus } from "@/hooks/use-options-data";

const groups = [
  { label:"Trade", items:[["Trade Desk","/",CircleGauge],["SPY / QQQ Options","/options",SlidersHorizontal],["Scanner","/scanner",ScanSearch],["Active Trades","/active-trades",Activity],["Journal",null,BookOpen]] },
  { label:"Analytics", items:[["Performance",null,ChartNoAxesCombined],["Research",null,SlidersHorizontal],["Reports",null,FileChartColumn]] },
  { label:"System", items:[["Alerts",null,Bell],["Data Health",null,HeartPulse],["Settings",null,Settings]] },
] as const;

function Brand() { return <div className="flex items-center gap-3"><div className="grid size-8 place-items-center rounded-lg border border-violet-400/30 bg-violet-400/10 text-sm font-black text-violet-200">OB</div><div><p className="text-sm font-bold tracking-tight text-white">OptionBeacon</p><p className="text-[9px] font-semibold uppercase tracking-[.18em] text-slate-600">Decision intelligence</p></div></div>; }

function Navigation({ close }: { close?:()=>void }) { const pathname=usePathname(); return <nav aria-label="Primary" className="mt-8 space-y-7">{groups.map(group=><div key={group.label}><p className="px-2 text-[9px] font-bold uppercase tracking-[.2em] text-slate-700">{group.label}</p><ul className="mt-2 space-y-1">{group.items.map(([name,href,Icon])=>{const active=href===pathname; return <li key={name}>{href ? <Link onClick={close} href={href} aria-current={active?"page":undefined} className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 text-xs font-semibold ${active?"border-violet-400/20 bg-violet-400/10 text-violet-100":"border-transparent text-slate-400 hover:bg-slate-900 hover:text-slate-200"}`}><Icon aria-hidden size={15}/><span>{name}</span>{active&&<ChevronRight aria-hidden className="ml-auto" size={13}/>}</Link> : <span aria-disabled className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2.5 text-xs font-medium text-slate-600"><Icon aria-hidden size={15}/><span>{name}</span><span className="ml-auto text-[8px] uppercase tracking-widest">Soon</span></span>}</li>})}</ul></div>)}</nav>; }

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open,setOpen]=useState(false); const [clock,setClock]=useState<Date|null>(null); const system=useSystemStatus();
  useEffect(()=>{const timer=setInterval(()=>setClock(new Date()),1000); return()=>clearInterval(timer)},[]);
  return <div className="min-h-screen lg:grid lg:grid-cols-[220px_1fr]">
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-[220px] border-r border-slate-800/80 bg-[#080c14] px-4 py-5 lg:block"><Brand/><Navigation/><p className="absolute bottom-5 left-5 text-[9px] uppercase tracking-[.15em] text-slate-700">React migration · Active Trades</p></aside>
    {open && <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm lg:hidden"><aside className="h-full w-[260px] border-r border-slate-800 bg-[#080c14] p-5"><div className="flex justify-between"><Brand/><button aria-label="Close navigation" onClick={()=>setOpen(false)} className="text-slate-400"><X size={20}/></button></div><Navigation close={()=>setOpen(false)}/></aside></div>}
    <div className="lg:col-start-2">
      <header className="sticky top-0 z-30 flex h-14 items-center border-b border-slate-800/80 bg-[#080c14]/90 px-4 backdrop-blur-xl sm:px-6 lg:px-8">
        <button aria-label="Open navigation" onClick={()=>setOpen(true)} className="mr-3 text-slate-400 lg:hidden"><Menu size={20}/></button><div className="lg:hidden"><Brand/></div>
        <div className="ml-auto flex items-center gap-2 sm:gap-4"><StatusBadge dot value={system.data?.market_status || "CLOSED"}/><div className="hidden items-center gap-2 sm:flex"><span className={`size-1.5 rounded-full ${system.data?.status === "ok" ? "bg-emerald-400" : "bg-amber-300"}`}/><span className="text-[10px] font-semibold uppercase tracking-[.1em] text-slate-400">API {system.error ? "offline" : system.data?.status || "connecting"}</span></div><span className="hidden h-4 w-px bg-slate-800 md:block"/><span className="hidden text-[10px] tabular-nums text-slate-500 md:block">{system.data ? `Data ${system.data.data_freshness}` : "Awaiting freshness"}</span><span className="font-mono text-[10px] tabular-nums text-slate-400">{clock ? timestamp(clock.toISOString()).replace(/:\d{2} /," ") : "--:-- ET"}</span></div>
      </header>
      <main>{children}</main>
    </div>
  </div>;
}
