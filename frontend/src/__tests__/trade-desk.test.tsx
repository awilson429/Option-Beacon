import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

const activeTrade = {
  id:"active-1", opportunity_id:"opp-1", symbol:"SPY", direction:"CALL", setup:"ORB", status:"OPEN",
  opened_at:"2026-08-24T14:22:00Z", closed_at:null, entry_price:1.2, last_price:1.35,
  exit_price:null, realized_result:null, exit_reason:null,
  metadata:{execution_lane:"BROAD", option_symbol:"SPY260824C00643000", unrealized_pnl:15},
};

const closedTrade = {
  id:"closed-1", opportunity_id:"opp-2", symbol:"QQQ", direction:"PUT", setup:"MIRROR_CONTROL", status:"CLOSED",
  opened_at:"2026-08-24T13:42:00Z", closed_at:"2026-08-24T14:04:00Z", entry_price:1.4,
  last_price:1.2, exit_price:1.15, realized_result:25, exit_reason:"TARGET", metadata:{},
};

const home = {
  as_of:"2026-08-24T14:30:00Z", data_status:"persisted",
  session:{realized_pnl:25,unrealized_pnl:15,total_pnl:40,trades:2,wins:1,losses:0,win_rate:100,active_trades:1},
  active:[], recent_activity:[],
  lanes:[
    {key:"OB",label:"OB",role:"AUTHORITATIVE",active_trades:0,trades_today:1,realized_pnl:25,description:"Authoritative OptionBeacon strategy"},
    {key:"BROAD",label:"BROAD",role:"PAPER",active_trades:1,trades_today:1,realized_pnl:null,description:"Broad-universe paper participation"},
    {key:"CONTROL_RESEARCH",label:"MIRROR / CONTROL RESEARCH",role:"RESEARCH_CONTROL",active_trades:0,trades_today:0,realized_pnl:null,description:"Research/control comparison only; not a primary live lane"},
  ],
  accounts:[
    {lane:"OB",data_status:"persisted",starting_capital:25000,current_equity:25640,cash_available:24400,capital_committed:1240,net_pnl:640,return_pct:2.56,realized_pnl:600,unrealized_pnl:40,fees:12,slippage:18,peak_equity:25800,current_drawdown_pct:.62,maximum_drawdown_pct:3.4,daily_pnl:90,open_risk:240,open_positions:2,risk_state:"NORMAL",readiness_status:"DEVELOPING",metrics:{trades:44,rejected_opportunities:7},updated_at:"2026-08-24T14:30:00Z"},
    {lane:"BROAD",data_status:"persisted",starting_capital:25000,current_equity:25120,cash_available:25120,capital_committed:0,net_pnl:120,return_pct:.48,realized_pnl:120,unrealized_pnl:0,fees:8,slippage:14,peak_equity:25300,current_drawdown_pct:.71,maximum_drawdown_pct:4.1,daily_pnl:25,open_risk:0,open_positions:0,risk_state:"WARNING",readiness_status:"EARLY_RESEARCH",metrics:{trades:22,rejected_opportunities:13},updated_at:"2026-08-24T14:30:00Z"},
  ],
  capital_decisions:[{decision_id:"d-1",lane:"OB",opportunity_id:"opp-1",symbol:"SPY",direction:"CALL",state:"TAKE",reason_code:"ALL_RISK_CONTROLS_PASSED",explanation:"Setup qualifies and all simulated-capital risk controls passed.",proposed_contract:"SPY260824C00643000",proposed_quantity:8,proposed_capital_required:1136,proposed_dollar_risk:112,proposed_account_risk_pct:.45,decided_at:"2026-08-24T14:30:00Z"}],
};

const system = {status:"ok",market_status:"open",database:"connected",data_freshness:"fresh",worker_status:"healthy",worker_last_success:"2026-08-24T14:29:00Z",provider_status:"not_queried",timestamp:"2026-08-24T14:30:00Z"};

function renderHome({ noActive=false, failRecent=false, pending=false } = {}) {
  vi.stubGlobal("fetch", vi.fn(async (input: string|URL|Request) => {
    if (pending) return new Promise<Response>(() => {});
    const path=String(input);
    if(path.endsWith("/api/trade-desk")) return Response.json(home);
    if(path.endsWith("/api/trades/active")) return Response.json(noActive?[]:[activeTrade]);
    if(path.includes("/api/trades/recent")) return failRecent?new Response("failed",{status:503}):Response.json([closedTrade]);
    if(path.endsWith("/api/system/status")) return Response.json(system);
    throw new Error(`Unexpected request ${path}`);
  }));
  return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><Home/></SWRConfig>);
}

afterEach(()=>{cleanup(); vi.unstubAllGlobals()});

describe("Trade Desk home",()=>{
  it("renders the root command center, primary navigation, session metrics, lanes, activity, and system health",async()=>{
    renderHome();
    expect(await screen.findByRole("heading",{name:"Trade Desk",level:1})).toBeInTheDocument();
    expect(screen.getByRole("link",{name:"Trade Desk"})).toHaveAttribute("aria-current","page");
    expect(screen.getByRole("link",{name:"SPY / QQQ Options"})).toHaveAttribute("href","/options");
    const session=screen.getByRole("heading",{name:"Authoritative persisted performance"}).closest("section")!;
    expect(within(session).getByText("$40.00")).toBeInTheDocument();
    expect(await screen.findByText("SPY260824C00643000")).toBeInTheDocument();
    expect(screen.getByText("MIRROR / CONTROL RESEARCH")).toBeInTheDocument();
    expect(screen.getByText("SHADOW")).toBeInTheDocument();
    expect(screen.getByText("Independent OB / BROAD accounts")).toBeInTheDocument();
    expect(screen.getByText("$25,640.00")).toBeInTheDocument();
    expect(screen.getByText("Why capital is or is not participating")).toBeInTheDocument();
    expect(screen.getByText("ALL RISK CONTROLS PASSED")).toBeInTheDocument();
    expect(await screen.findByText("Persisted trade events")).toBeInTheDocument();
    expect(screen.getByText("Operational summary")).toBeInTheDocument();
  });

  it("shows a truthful empty state when no trade is active",async()=>{
    renderHome({noActive:true});
    expect(await screen.findByText("No active trades")).toBeInTheDocument();
    expect(screen.getByText("OptionBeacon is monitoring current opportunities.")).toBeInTheDocument();
  });

  it("isolates a recent-activity failure while active trades stay usable",async()=>{
    renderHome({failRecent:true});
    expect(await screen.findByText("SPY260824C00643000")).toBeInTheDocument();
    await waitFor(()=>expect(screen.getByText("Recent activity unavailable")).toBeInTheDocument());
    expect(screen.getByText("Other desk data will continue updating.")).toBeInTheDocument();
  });

  it("presents loading states without fabricated data",()=>{
    renderHome({pending:true});
    expect(screen.getByLabelText("Loading session summary")).toBeInTheDocument();
    expect(screen.queryByText("$40.00")).not.toBeInTheDocument();
  });
});
