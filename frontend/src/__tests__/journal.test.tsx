import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";
import JournalPage from "@/app/journal/page";
import type { JournalResponse, JournalTrade, TradeManagementSnapshot } from "@/lib/types";

vi.mock("next/navigation",()=>({usePathname:()=>"/journal"}));

const system={status:"ok",market_status:"closed",database:"connected",data_freshness:"fresh",worker_status:"healthy",worker_last_success:"2026-08-25T16:00:00Z",provider_status:"not_queried",timestamp:"2026-08-25T16:00:00Z"};
const metrics={total_trades:2,wins:1,losses:1,breakeven:0,win_rate:50,realized_pnl:15,average_winner:35,average_loser:-20,profit_factor:1.75,average_return_pct:4.35,average_hold_seconds:690};

const ob:JournalTrade={trade_id:"OB:paper-1",opportunity_id:"opp-1",lane:"OB",lane_role:"AUTHORITATIVE",symbol:"QQQ",direction:"CALL",status:"CLOSED",strategy:"OB",contract_symbol:"QQQ260825C00713000",strike:713,option_type:"CALL",expiration:"2026-08-25",dte:0,quantity:2,entry_timestamp:"2026-08-25T15:48:00Z",underlying_entry:713.1,option_entry_premium:1.42,capital_committed:284,initial_dollar_risk:56,exit_timestamp:"2026-08-25T16:00:00Z",underlying_exit:714.2,option_exit_premium:1.62,exit_reason:"TARGET",hold_duration_seconds:720,realized_pnl:35,realized_return_pct:15.71,r_multiple:.625,mfe_dollars:52,mae_dollars:-18,mfe_pct:18.57,mae_pct:-6.43,result:"WIN",initial_stop:712.5,target_1:714,target_2:714.8,target_3:715.5,management_history_available:true,management_snapshot_count:1,final_exit_score:64,final_management_label:"PROTECT",final_management_at:"2026-08-25T15:58:00Z",data_quality:"CANONICAL",missing_data:[],source_version:"scanner-v7"};
const broad:JournalTrade={...ob,trade_id:"BROAD:paper-2",opportunity_id:"opp-2",lane:"BROAD",lane_role:"PAPER",symbol:"SPY",direction:"PUT",contract_symbol:"SPY260825P00642000",quantity:1,realized_pnl:-20,realized_return_pct:-7.01,result:"LOSS",exit_reason:"STOP",management_history_available:false,management_snapshot_count:0,final_exit_score:null,final_management_label:null,final_management_at:null,missing_data:["canonical_management_history"]};

const history:JournalResponse={as_of:"2026-08-25T16:00:00Z",data_status:"persisted",total_count:2,limit:200,offset:0,summary:metrics,lanes:[{lane:"OB",...metrics,total_trades:1,wins:1,losses:0,win_rate:100,realized_pnl:35,average_return_pct:15.71,profit_factor:null},{lane:"BROAD",...metrics,total_trades:1,wins:0,losses:1,win_rate:0,realized_pnl:-20,average_return_pct:-7.01,profit_factor:0}],control_research:null,trades:[ob,broad]};
const snapshot:TradeManagementSnapshot={snapshot_id:"snap-1",trade_id:ob.trade_id,opportunity_id:ob.opportunity_id,lane:"OB",lane_role:"AUTHORITATIVE",symbol:"QQQ",contract_symbol:ob.contract_symbol,captured_at:"2026-08-25T15:58:00Z",source_timestamp:"2026-08-25T15:58:00Z",trade_status:"OPEN",quantity:2,entry_timestamp:ob.entry_timestamp,entry_premium:1.42,latest_option_mark:1.57,latest_underlying:714,mark_timestamp:"2026-08-25T15:58:00Z",time_in_trade_seconds:600,current_stop:713.3,target_1:714,target_2:714.8,target_3:715.5,breakeven_state:"ACTIVE",maximum_hold_minutes:15,exit_score:64,exit_label:"PROTECT",trade_coach_state:"THESIS_INTACT",thesis_state:"INTACT",momentum_state:"WEAKENING",structure_state:"ABOVE_VWAP",target_progress:"T1_REACHED",stop_management_state:"BREAKEVEN",management_reason:"MOMENTUM_WEAKENING",management_version:"test-v1",management_source:"test",unrealized_pnl:30,unrealized_return_pct:10,current_managed_risk:20,data_freshness:"fresh",stale:false,missing_data:[],state_fingerprint:"abc"};

function renderPage({payload=history,pending=false,fail=false,management=[snapshot]}:{payload?:JournalResponse;pending?:boolean;fail?:boolean;management?:TradeManagementSnapshot[]}={}){
  vi.stubGlobal("fetch",vi.fn(async(input:string|URL|Request)=>{const path=String(input);if(path.endsWith("/api/system/status"))return Response.json(system);if(path.includes("/api/trades/history?")){if(pending)return new Promise<Response>(()=>{});if(fail)return new Response("failed",{status:503});return Response.json(payload)}if(path.includes("/management?lane="))return Response.json(management);throw new Error(`Unexpected request ${path}`)}));
  return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><JournalPage/></SWRConfig>);
}

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

describe("Journal page",()=>{
  it("renders enabled navigation, summary, OB/BROAD breakdown, and history",async()=>{
    renderPage();expect(await screen.findByRole("heading",{name:"Journal",level:1})).toBeInTheDocument();const link=screen.getByRole("link",{name:"Journal"});expect(link).toHaveAttribute("href","/journal");expect(link).toHaveAttribute("aria-current","page");const summary=screen.getByRole("heading",{name:"Performance summary"}).closest("section")!;expect(within(summary).getByText("$15.00")).toHaveClass("text-emerald-300");expect(within(summary).getByText("50%")).toBeInTheDocument();expect(screen.getAllByText("QQQ260825C00713000").length).toBeGreaterThan(0);expect(screen.getAllByText("SPY260825P00642000").length).toBeGreaterThan(0);expect(screen.getByText("MIRROR excluded from deployable performance")).toBeInTheDocument();
  });

  it("styles positive and negative P&L without hiding missing values",async()=>{renderPage();expect((await screen.findAllByText("$35.00"))[0]).toHaveClass("text-emerald-300");expect(screen.getAllByText("-$20.00")[0]).toHaveClass("text-rose-300");});

  it("updates filters without a page reload",async()=>{renderPage();await screen.findByText("Trade history");fireEvent.change(screen.getByLabelText("Lane"),{target:{value:"BROAD"}});await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes("lane=BROAD"))).toBe(true));fireEvent.change(screen.getByLabelText("Result"),{target:{value:"LOSS"}});await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes("result=LOSS"))).toBe(true));});

  it("opens a trade detail and loads its exact canonical timeline",async()=>{renderPage();const user=userEvent.setup();await user.click((await screen.findAllByText("QQQ260825C00713000"))[0]);expect(screen.getByRole("dialog",{name:"Trade detail"})).toBeInTheDocument();expect(screen.getByText("Management timeline")).toBeInTheDocument();expect(await screen.findByText("Exit Score 64")).toBeInTheDocument();expect(screen.getByText("Momentum WEAKENING")).toBeInTheDocument();expect(screen.getByText("ENTRY")).toBeInTheDocument();expect(screen.getByText("EXIT")).toBeInTheDocument();expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes("OB%3Apaper-1/management?lane=OB"))).toBe(true);});

  it("shows an intentional legacy management state",async()=>{renderPage();const user=userEvent.setup();await user.click((await screen.findAllByText("SPY260825P00642000"))[0]);expect(screen.getByText("Canonical management history is unavailable for this trade.")).toBeInTheDocument();expect(screen.getByText(/Canonical management history/)).toBeInTheDocument();expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).includes("/management?")).length).toBe(0);});

  it("shows an empty state when filters have no completed trades",async()=>{renderPage({payload:{...history,total_count:0,summary:{...metrics,total_trades:0,realized_pnl:null},trades:[]}});expect(await screen.findByText("No historical trades")).toBeInTheDocument();expect(screen.getByText("No completed trades match the selected filters.")).toBeInTheDocument();});

  it("renders skeletons while history loads",()=>{const view=renderPage({pending:true});expect(view.container.querySelectorAll(".skeleton").length).toBeGreaterThan(5);expect(screen.queryByText("QQQ260825C00713000")).not.toBeInTheDocument();});

  it("isolates an API failure behind a retry state",async()=>{renderPage({fail:true});expect(await screen.findByText("Journal history is unavailable")).toBeInTheDocument();expect(screen.getByRole("button",{name:"Retry"})).toBeInTheDocument();expect(screen.getAllByText("CLOSED").length).toBeGreaterThan(0);});

  it("renders compact mobile history controls in the same DOM contract",async()=>{renderPage();expect(await screen.findByLabelText("Journal filters")).toBeInTheDocument();const mobileButton=screen.getAllByRole("button").find(button=>button.textContent?.includes("QQQ260825C00713000"));expect(mobileButton).toHaveClass("w-full");});
});
