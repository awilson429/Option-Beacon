import { cleanup, render, screen, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";
import ScannerPage from "@/app/scanner/page";
import type { ScannerResponse } from "@/lib/types";

vi.mock("next/navigation",()=>({usePathname:()=>"/scanner"}));

const scanner:ScannerResponse={
  as_of:"2026-08-24T15:00:00Z",market_status:"open",data_status:"persisted",research_control_role:"RESEARCH_CONTROL_ONLY",
  health:{state:"CURRENT",message:"Scanner data is current.",market_data_state:"AVAILABLE",worker_status:"healthy",provider_status:"not_queried",data_freshness:"fresh",last_started_at:"2026-08-24T14:58:30Z",last_completed_at:"2026-08-24T14:59:00Z",last_success_at:"2026-08-24T14:59:00Z",last_error_at:null,last_error_message:null,scan_duration_seconds:20,symbols_processed:74,symbols_attempted:74,symbol_count:74,results:74,failures:0,expected_interval_seconds:300,next_expected_at:"2026-08-24T15:04:00Z"},
  instruments:[
    {symbol:"SPY",data_status:"persisted",underlying_price:642.31,direction:"Bullish",setup:"VWAP continuation",score:81,confidence:78,signal_state:"OPEN",observed_at:"2026-08-24T14:58:00Z",signal_age_seconds:120,freshness:"fresh",actionable:true,context:{regime:"range_chop"}},
    {symbol:"QQQ",data_status:"unavailable",underlying_price:null,direction:null,setup:null,score:null,confidence:null,signal_state:"UNAVAILABLE",observed_at:null,signal_age_seconds:null,freshness:"unavailable",actionable:false,context:{}},
  ],
  opportunities:[{opportunity_id:"opp-1",symbol:"SPY",direction:"Bullish",strategy:"VWAP continuation",observed_at:"2026-08-24T14:58:00Z",score:81,confidence:78,contract:"SPY260824C00643000",entry:642.25,stop:641.82,targets:[642.9,643.4],status:"OPEN",actionable:true,data_status:"persisted",freshness:"fresh",context:{regime:"range_chop"},lane_decisions:[
    {lane:"OB",data_status:"persisted",state:"TAKE",reason_code:"ALL_RISK_CONTROLS_PASSED",explanation:"OB controls passed.",proposed_contract:"SPY260824C00643000",proposed_quantity:2,proposed_capital_required:228,proposed_dollar_risk:56,proposed_account_risk_pct:.22,decided_at:"2026-08-24T14:59:00Z"},
    {lane:"BROAD",data_status:"persisted",state:"PASS",reason_code:"CONTRACT_SPREAD_TOO_WIDE",explanation:"Spread exceeds the BROAD lane limit.",proposed_contract:"SPY260824C00643000",proposed_quantity:0,proposed_capital_required:0,proposed_dollar_risk:0,proposed_account_risk_pct:0,decided_at:"2026-08-24T14:59:00Z"},
  ]}],
  recent_activity:[{activity_id:"d-1",event_type:"LANE_DECISION",occurred_at:"2026-08-24T14:59:00Z",symbol:"SPY",direction:"CALL",opportunity_id:"opp-1",lane:"BROAD",status:"PASS",reason_code:"CONTRACT_SPREAD_TOO_WIDE",description:"Spread exceeds the BROAD lane limit."}],
  sections:[{section:"scanner_health",data_status:"persisted",message:null},{section:"opportunities",data_status:"persisted",message:null},{section:"lane_decisions",data_status:"persisted",message:null},{section:"recent_activity",data_status:"persisted",message:null}],
};

const system={status:"ok",market_status:"open",database:"connected",data_freshness:"fresh",worker_status:"healthy",worker_last_success:"2026-08-24T14:59:00Z",provider_status:"not_queried",timestamp:"2026-08-24T15:00:00Z"};

function renderScanner(payload:ScannerResponse=scanner,{pending=false}={}) {
  vi.stubGlobal("fetch",vi.fn(async(input:string|URL|Request)=>{
    const path=String(input);
    if(path.endsWith("/api/system/status")) return Response.json(system);
    if(path.endsWith("/api/scanner")) return pending?new Promise<Response>(()=>{}):Response.json(payload);
    throw new Error(`Unexpected request ${path}`);
  }));
  return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><ScannerPage/></SWRConfig>);
}

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

describe("Scanner page",()=>{
  it("renders navigation, SPY/QQQ cards, actionable setup, OB/BROAD decisions, and demoted MIRROR",async()=>{
    renderScanner();
    expect(await screen.findByRole("heading",{name:"Scanner",level:1})).toBeInTheDocument();
    const nav=screen.getByRole("link",{name:"Scanner"});
    expect(nav).toHaveAttribute("href","/scanner"); expect(nav).toHaveAttribute("aria-current","page");
    const spy=screen.getByTestId("scanner-SPY"); const qqq=screen.getByTestId("scanner-QQQ");
    expect(within(spy).getByText("$642.31")).toBeInTheDocument();
    expect(within(spy).getByText("81")).toBeInTheDocument();
    expect(within(qqq).getByText("No qualifying setup right now")).toBeInTheDocument();
    expect(screen.getAllByText("SPY260824C00643000").length).toBeGreaterThan(0);
    expect(screen.getAllByText("OB").length).toBeGreaterThan(0); expect(screen.getByText("BROAD")).toBeInTheDocument();
    expect(screen.getByText("ALL RISK CONTROLS PASSED")).toBeInTheDocument();
    expect(screen.getAllByText("CONTRACT SPREAD TOO WIDE").length).toBeGreaterThan(0);
    expect(screen.getByText("MIRROR / CONTROL RESEARCH")).toBeInTheDocument();
    expect(screen.getByText(/research-only and is not a capital lane/i)).toBeInTheDocument();
  });

  it("shows an intentional no-opportunity state",async()=>{
    renderScanner({...scanner,opportunities:[],instruments:scanner.instruments.map(item=>({...item,data_status:"unavailable",underlying_price:null,direction:null,setup:null,score:null,confidence:null,signal_state:"UNAVAILABLE",observed_at:null,signal_age_seconds:null,freshness:"unavailable",actionable:false,context:{}}))});
    expect((await screen.findAllByText("No qualifying setup right now")).length).toBe(3);
    expect(screen.getByText(/Inactivity is an intentional scanner state/i)).toBeInTheDocument();
  });

  it("presents loading skeletons without invented scanner values",()=>{
    renderScanner(scanner,{pending:true});
    expect(screen.getByLabelText("Loading scanner")).toBeInTheDocument();
    expect(screen.queryByText("SPY260824C00643000")).not.toBeInTheDocument();
  });

  it("isolates a partial opportunity API failure while instrument state remains usable",async()=>{
    const partial={...scanner,data_status:"partial",opportunities:[],sections:scanner.sections.map(item=>item.section==="opportunities"?{...item,data_status:"error",message:"Persisted opportunities could not be read."}:item)};
    renderScanner(partial);
    expect(await screen.findByText("$642.31")).toBeInTheDocument();
    expect(screen.getByText("Scanner opportunities unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("scanner-QQQ")).toBeInTheDocument();
  });

  it("warns clearly when scanner data is stale",async()=>{
    renderScanner({...scanner,health:{...scanner.health,state:"STALE",worker_status:"degraded",data_freshness:"stale",message:"Scanner data is stale."}});
    expect(await screen.findByRole("alert")).toHaveTextContent("Stale scanner data");
    expect(screen.getAllByText("STALE").length).toBeGreaterThan(0);
    expect(screen.getByText(/Review the last-success time before acting/i)).toBeInTheDocument();
  });
});
