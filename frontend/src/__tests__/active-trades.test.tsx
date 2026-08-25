import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";
import ActiveTradesPage from "@/app/active-trades/page";
import type { ActiveTrade } from "@/lib/types";

vi.mock("next/navigation",()=>({usePathname:()=>"/active-trades"}));

const system={status:"ok",market_status:"open",database:"connected",data_freshness:"fresh",worker_status:"healthy",worker_last_success:"2026-08-24T14:59:00Z",provider_status:"not_queried",timestamp:"2026-08-24T15:00:00Z"};

const ob:ActiveTrade={
  id:"OB:paper-1",opportunity_id:"opp-1",symbol:"QQQ",direction:"CALL",setup:"VWAP_CONTINUATION",status:"OPEN",
  opened_at:"2026-08-24T14:53:00Z",closed_at:null,entry_price:713.1,last_price:713.8,exit_price:null,realized_result:null,exit_reason:null,metadata:{},
  lane:"OB",lane_role:"AUTHORITATIVE",strategy:"OB",data_status:"persisted",contract_symbol:"QQQ260824C00713000",strike:713,option_type:"CALL",expiration:"2026-08-24",dte:0,quantity:8,
  entry_timestamp:"2026-08-24T14:53:00Z",underlying_entry:713.1,option_entry_premium:1.42,capital_committed:1136,initial_dollar_risk:112,account_risk_pct:.45,current_dollar_risk:null,
  latest_underlying:713.8,latest_option_mark:1.61,unrealized_pnl:152,unrealized_return_pct:13.4,time_in_trade_seconds:420,data_freshness:"fresh",mark_timestamp:"2026-08-24T14:59:40Z",
  stop:712.6,target_1:714,target_2:714.8,target_3:715.5,breakeven_state:null,maximum_hold_minutes:null,exit_score:76,exit_state:"HOLD",trade_coach_status:"THESIS_INTACT",thesis_status:"INTACT",momentum_state:"MODERATING",structure_state:"ABOVE_VWAP",target_progress:"APPROACHING_T1",stop_management_state:null,last_management_update:"2026-08-24T14:59:30Z",management_data_status:"persisted",
};

const broad:ActiveTrade={...ob,id:"BROAD:paper-2",opportunity_id:"opp-2",symbol:"SPY",direction:"PUT",lane:"BROAD",lane_role:"PAPER",strategy:"BROAD",contract_symbol:"SPY260824P00642000",strike:642,option_type:"PUT",quantity:3,underlying_entry:642.4,latest_underlying:642.7,option_entry_premium:1.18,latest_option_mark:null,unrealized_pnl:-24,unrealized_return_pct:-6.8,capital_committed:354,initial_dollar_risk:48,account_risk_pct:.19,data_freshness:"stale",mark_timestamp:"2026-08-24T14:38:00Z",stop:643.1,target_1:641.8,target_2:641.2,target_3:null,exit_score:null,exit_state:null,trade_coach_status:null,thesis_status:null,momentum_state:null,structure_state:null,target_progress:null,last_management_update:null,management_data_status:"unavailable"};

function renderPage({trades=[ob,broad],pending=false,fail=false}:{trades?:ActiveTrade[];pending?:boolean;fail?:boolean}={}) {
  vi.stubGlobal("fetch",vi.fn(async(input:string|URL|Request)=>{
    const path=String(input);
    if(path.endsWith("/api/system/status")) return Response.json(system);
    if(path.endsWith("/api/trades/active")) {
      if(pending) return new Promise<Response>(()=>{});
      if(fail) return new Response("failed",{status:503});
      return Response.json(trades);
    }
    throw new Error(`Unexpected request ${path}`);
  }));
  return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><ActiveTradesPage/></SWRConfig>);
}

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

describe("Active Trades page",()=>{
  it("renders the route, active navigation, summary, and exact OB/BROAD ownership",async()=>{
    renderPage();
    expect(await screen.findByRole("heading",{name:"Active Trades",level:1})).toBeInTheDocument();
    const activeLink=screen.getByRole("link",{name:"Active Trades"});
    expect(activeLink).toHaveAttribute("href","/active-trades");
    expect(activeLink).toHaveAttribute("aria-current","page");
    expect(screen.getByRole("link",{name:"Scanner"})).toHaveAttribute("href","/scanner");
    expect(screen.getByRole("link",{name:"Journal"})).toHaveAttribute("href","/journal");
    const summary=screen.getByRole("heading",{name:"Open-position summary"}).closest("section")!;
    expect(within(summary).getByText("2")).toBeInTheDocument();
    expect(within(summary).getByText("$1,490.00")).toBeInTheDocument();
    expect(screen.getAllByText("OB").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BROAD").length).toBeGreaterThan(0);
    expect(screen.queryByText("MIRROR",{exact:true})).not.toBeInTheDocument();
  });

  it("renders contract, plan, management, positive P&L, and time for an active position",async()=>{
    renderPage({trades:[ob]});
    const card=await screen.findByTestId("active-trade-OB:paper-1");
    expect(within(card).getByText("QQQ260824C00713000")).toBeInTheDocument();
    expect(within(card).getByText("8 contracts · 0DTE")).toBeInTheDocument();
    expect(within(card).getByText("$152.00")).toHaveClass("text-emerald-300");
    expect(within(card).getByText("13.4%")).toBeInTheDocument();
    expect(within(card).getByText("7m 0s")).toBeInTheDocument();
    expect(within(card).getByText("76")).toBeInTheDocument();
    expect(within(card).getByText("HOLD")).toBeInTheDocument();
    expect(within(card).getByText("THESIS INTACT")).toBeInTheDocument();
    expect(within(card).getByLabelText("Trade plan progress")).toBeInTheDocument();
  });

  it("isolates negative P&L, a missing mark, stale state, and unavailable management",async()=>{
    renderPage({trades:[broad]});
    const card=await screen.findByTestId("active-trade-BROAD:paper-2");
    expect(within(card).getByText("-$24.00")).toHaveClass("text-rose-300");
    expect(within(card).getByText("Price unavailable",{selector:"strong"})).toBeInTheDocument();
    expect(within(card).getByText(/Mark stale · position details remain visible/i)).toBeInTheDocument();
    expect(within(card).getByText("Management state unavailable")).toBeInTheDocument();
    expect(within(card).getByText(/No canonically attributable Trade Coach/i)).toBeInTheDocument();
  });

  it("shows an intentional empty state",async()=>{
    renderPage({trades:[]});
    expect(await screen.findByText("No active trades")).toBeInTheDocument();
    expect(screen.getByText("OptionBeacon is monitoring the market for qualified opportunities.")).toBeInTheDocument();
  });

  it("shows skeleton position cards while the active endpoint loads",()=>{
    renderPage({pending:true});
    expect(screen.getByLabelText("Loading active trades")).toBeInTheDocument();
    expect(screen.queryByText("QQQ260824C00713000")).not.toBeInTheDocument();
  });

  it("shows a page-level active-trades error with retry while system state remains isolated",async()=>{
    renderPage({fail:true});
    await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("Active trades unavailable"));
    expect(screen.getByRole("button",{name:"Retry"})).toBeInTheDocument();
    expect(screen.getAllByText("OPEN").length).toBeGreaterThan(0);
  });
});
