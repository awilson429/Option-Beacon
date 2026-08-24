import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OptionsDesk } from "@/components/options-desk";
import type { StrategyState } from "@/lib/types";

const strategy = (symbol: "SPY"|"QQQ", direction: "CALL"|"PUT", contract: string|null): StrategyState => ({
  symbol, price: symbol === "SPY" ? 642.18 : 571.42, market_status:"open", data_status:"persisted", last_updated:"2026-08-24T14:30:00Z",
  bias:{direction,label:`${direction} BIAS`}, trade_coverage:{direction,entry_trigger:symbol==="SPY"?642.25:571.2,state:symbol==="SPY"?"READY":"WATCHING"},
  setup:{state:contract?"selected":"awaiting_contract",strike:contract?643:null,expiration:contract?"2026-08-24":null,dte:contract?0:null,spread:contract?3.5:null,contract,
    entry_zone:symbol==="SPY"?[642.12,642.24]:null,maximum_chase:symbol==="SPY"?642.48:null,stop:symbol==="SPY"?641.82:null,targets:symbol==="SPY"?[642.9,643.4]:null,risk_reward:symbol==="SPY"?1.9:null},
  context:{level:"available",known_factors:["vwap_aligned"],details:null},confirmations:{state:"context_only",items:["EMA aligned"]},market_condition:{regime:"RANGE / CHOP"},session:{pnl:null,trades:0,wins:0,losses:0,win_rate:null},
});

function payload(path: string) {
  if(path.endsWith("/options-desk/SPY")) return strategy("SPY","CALL","SPY260824C00643000");
  if(path.endsWith("/options-desk/QQQ")) return strategy("QQQ","PUT",null);
  if(path.endsWith("/scalp/SPY")) return {symbol:"SPY",strategy:"SCALP_RESEARCH",mode:"SHADOW",market_status:"open",data_status:"persisted",current:{direction:"CALL",setup_family:"VWAP_CONTINUATION",state:"FORMING",entry_trigger:642.3,invalidation:641.9,maximum_chase:642.5,expected_hold_minutes:[3,15]}};
  if(path.endsWith("/scalp/QQQ")) return {symbol:"QQQ",strategy:"SCALP_RESEARCH",mode:"SHADOW",market_status:"open",data_status:"unavailable",current:null};
  if(path.includes("/performance")) return {symbol:path.includes("SPY")?"SPY":"QQQ",strategy:"SCALP_RESEARCH",metrics:{triggered_trades:8,win_rate:50,expectancy:3,profit_factor:1.1,net_simulated_pnl:24,maximum_drawdown:40,average_hold_minutes:6,evidence:"INSUFFICIENT"}};
  if(path.endsWith("/scalp/compare")) return {strategy:"SCALP_RESEARCH",symbols:{SPY:{triggered_trades:8,evidence:"INSUFFICIENT"},QQQ:{triggered_trades:7,evidence:"INSUFFICIENT"}},normalization:"per triggered contract; realistic P&L primary"};
  throw new Error(`Unexpected request ${path}`);
}

function renderDesk(failSpy=false) {
  vi.stubGlobal("fetch",vi.fn(async(input: string|URL|Request)=>{
    const path=String(input); if(failSpy && path.endsWith("/options-desk/SPY")) return new Response("failed",{status:503});
    return new Response(JSON.stringify(payload(path)),{status:200,headers:{"Content-Type":"application/json"}});
  }));
  return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><OptionsDesk/></SWRConfig>);
}

afterEach(()=>{cleanup(); vi.unstubAllGlobals()});

describe("Options Desk",()=>{
  it("renders independent SPY CALL and QQQ PUT states with responsive equal-weight panels",async()=>{
    const {container}=renderDesk();
    const spy=await screen.findByTestId("instrument-SPY"); const qqq=await screen.findByTestId("instrument-QQQ");
    expect(within(spy).getAllByText("CALL").length).toBeGreaterThan(0); expect(within(qqq).getAllByText("PUT").length).toBeGreaterThan(0);
    expect(within(spy).getByText("SPY260824C00643000")).toBeInTheDocument(); expect(within(qqq).getByText("Awaiting contract")).toBeInTheDocument();
    expect(container.querySelector(".xl\\:grid-cols-2")).toBeInTheDocument();
  });

  it("labels shadow research, progression, empty state, and insufficient evidence",async()=>{
    renderDesk(); const spy=await screen.findByTestId("instrument-SPY"); const qqq=await screen.findByTestId("instrument-QQQ");
    expect(within(spy).getByText("SHADOW")).toBeInTheDocument();
    expect(within(spy).getByText("Research simulation only. Does not affect live OptionBeacon recommendations.")).toBeInTheDocument();
    expect(within(spy).getByText("FORMING")).toHaveAttribute("aria-current","step");
    expect(within(qqq).getByText("No active research setup")).toBeInTheDocument();
    expect((await screen.findAllByText("INSUFFICIENT EVIDENCE")).length).toBeGreaterThan(0);
    expect(screen.getByText("NO WINNER · INSUFFICIENT EVIDENCE")).toBeInTheDocument();
  });

  it("isolates a failed SPY strategy request while QQQ remains usable",async()=>{
    renderDesk(true); const qqq=await screen.findByTestId("instrument-QQQ");
    expect(within(qqq).getAllByText("PUT").length).toBeGreaterThan(0);
    await waitFor(()=>expect(screen.getByText("SPY strategy unavailable")).toBeInTheDocument());
    expect(screen.getByRole("button",{name:"Retry"})).toBeInTheDocument();
  });
});
