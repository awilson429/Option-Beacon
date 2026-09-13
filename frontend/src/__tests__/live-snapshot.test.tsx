import {cleanup,render,screen,within} from "@testing-library/react";
import {SWRConfig} from "swr";
import {afterEach,describe,expect,it,vi} from "vitest";
import LiveSnapshotPage from "@/app/diagnostics/live-snapshot/page";
import type {LiveSnapshot} from "@/lib/types";

vi.mock("next/navigation",()=>({usePathname:()=>"/diagnostics/live-snapshot"}));
const system={status:"ok",market_status:"open",database:"connected",data_freshness:"fresh",worker_status:"healthy",worker_last_success:"2026-09-13T14:30:00Z",provider_status:"not_queried",timestamp:"2026-09-13T14:30:00Z"};
const scanner={symbol:"SPY" as const,data_status:"persisted",underlying_price:500.25,direction:"CALL",setup:"ORB",score:81,confidence:.8,signal_state:"OPEN",observed_at:"2026-09-13T14:30:00Z",signal_age_seconds:0,freshness:"fresh",actionable:true,context:{}};
const snapshot:LiveSnapshot={schema_version:"1",generated_at:"2026-09-13T14:30:00Z",data_status:"partial",market:{session_date:"2026-09-13",session_state:"open",last_authoritative_data_at:"2026-09-13T14:30:00Z",freshness:"fresh"},symbols:{SPY:{symbol:"SPY",data_status:"persisted",observation:{observation_id:"obs-1",scan_cycle_id:"cycle-1",observed_at:"2026-09-13T14:30:00Z",underlying_price:500.25,direction:"CALL",qualification_state:"TAKE",reason_code:"QUALIFIED",total_score:81,indicators:{}},scanner,latest_decisions:[]},QQQ:{symbol:"QQQ",data_status:"unavailable",observation:null,scanner:{...scanner,symbol:"QQQ",data_status:"unavailable",underlying_price:null,score:null,setup:null},latest_decisions:[]}},scanner:{cycle_id:"cycle-1",cycle_timestamp:"2026-09-13T14:30:00Z",cycle_completion_state:"COMPLETED",latest_processed_symbols:["SPY"],status:"CURRENT",last_successful_completed_cycle:"2026-09-13T14:30:00Z",health:{state:"CURRENT",message:"Current",market_data_state:"AVAILABLE",worker_status:"healthy",provider_status:"not_queried",data_freshness:"fresh",last_started_at:"2026-09-13T14:30:00Z",last_completed_at:"2026-09-13T14:30:00Z",last_success_at:"2026-09-13T14:30:00Z",last_error_at:null,last_error_message:null,scan_duration_seconds:2,symbols_processed:2,symbols_attempted:2,symbol_count:2,results:2,failures:0,expected_interval_seconds:300,next_expected_at:null}},decisions:[{decision_id:"d1",opportunity_id:"opp-1",symbol:"SPY",lane:"OB",timestamp:"2026-09-13T14:30:00Z",action:"TAKE",score:81,setup:"ORB",direction:"CALL",reason_code:"QUALIFIED",explanation:"Persisted",observation_id:"obs-1",scan_cycle_id:"cycle-1"}],active_trades:[],recent_trades:[],system:{state:system,coverage:{SPY:"persisted",QQQ:"unavailable"},provenance:{},stale_or_missing:["QQQ"]},provenance:{data_status:"persisted",observation_count:1,schema:"canonical_decision_observations"}};

function show(payload:LiveSnapshot=snapshot,mode:"ok"|"pending"|"error"="ok"){
 vi.stubGlobal("fetch",vi.fn(async(input:string|URL|Request)=>{const path=String(input);if(path.endsWith("/api/system/status"))return Response.json(system);if(path.endsWith("/api/live/snapshot")){if(mode==="pending")return new Promise<Response>(()=>{});if(mode==="error")return new Response(null,{status:503});return Response.json(payload)}throw new Error(path)}));
 return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><LiveSnapshotPage/></SWRConfig>);
}
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
describe("live snapshot diagnostics",()=>{
 it("renders connection, symbols, cycle and decisions",async()=>{show();expect(await screen.findByRole("heading",{name:"Canonical Live Snapshot"})).toBeInTheDocument();expect(screen.getByText("Connected")).toBeInTheDocument();expect(within(screen.getByTestId("snapshot-SPY")).getByText("500.25")).toBeInTheDocument();expect(screen.getByText("cycle-1")).toBeInTheDocument();expect(screen.getAllByText("QUALIFIED").length).toBeGreaterThan(0)});
 it("shows loading state",()=>{show(snapshot,"pending");expect(screen.getByLabelText("Loading live snapshot")).toBeInTheDocument()});
 it("shows backend unavailable state",async()=>{show(snapshot,"error");expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable")});
 it("renders null values as unavailable rather than zero",async()=>{show();const qqq=await screen.findByTestId("snapshot-QQQ");expect(within(qqq).getAllByText("Unavailable").length).toBeGreaterThan(0);expect(within(qqq).getByText(/no value was inferred/i)).toBeInTheDocument()});
});
