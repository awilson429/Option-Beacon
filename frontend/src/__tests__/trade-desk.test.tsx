import {act,cleanup,render,screen,waitFor,within} from "@testing-library/react";
import {SWRConfig} from "swr";
import {afterEach,describe,expect,it,vi} from "vitest";
import Home from "@/app/page";
import {SNAPSHOT_POLL_INTERVAL_MS} from "@/hooks/use-options-data";
import {snapshot,system} from "./live-snapshot-fixture";

vi.mock("next/navigation",()=>({usePathname:()=>"/"}));
function renderHome(responses:(Response|Promise<Response>)[]=[Response.json(snapshot)]){
 let index=0;
 vi.stubGlobal("fetch",vi.fn(async(input:string|URL|Request)=>{const path=String(input);if(path.endsWith("/api/system/status"))return Response.json(system);if(path.endsWith("/api/live/snapshot"))return responses[Math.min(index++,responses.length-1)];throw new Error(path)}));
 return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><Home/></SWRConfig>);
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.useRealTimers()});
describe("primary trading terminal",()=>{
 it("renders healthy state, SPY TAKE, QQQ rejection, indicators, decision and active/recent trades",async()=>{renderHome();expect(await screen.findByRole("heading",{name:"Market Command"})).toBeInTheDocument();expect(within(screen.getByTestId("setup-SPY")).getByText("TAKE")).toBeInTheDocument();expect(within(screen.getByTestId("setup-QQQ")).getByText("REJECTED")).toBeInTheDocument();expect(screen.getByText("EMA 9")).toBeInTheDocument();expect(screen.getAllByText("ALL RISK CONTROLS PASSED").length).toBeGreaterThan(0);expect(screen.getByText("trade-1")).toBeInTheDocument();expect(screen.getByText("$30.00")).toBeInTheDocument();expect(screen.getByText("Compact authoritative history")).toBeInTheDocument();expect(screen.getByText("System & provenance")).toBeInTheDocument()});
 it("shows null numbers as unavailable and never as zero",async()=>{renderHome();const qqq=await screen.findByTestId("setup-QQQ");expect(within(qqq).getAllByText("Unavailable").length).toBeGreaterThan(0);expect(within(qqq).queryByText("$0.00")).not.toBeInTheDocument()});
 it("renders stale and degraded authoritative health",async()=>{renderHome([Response.json({...snapshot,market:{...snapshot.market,freshness:"stale"},scanner:{...snapshot.scanner,status:"STALE"},system:{...snapshot.system,state:{...system,worker_status:"degraded"},stale_or_missing:["scanner_stale_or_unavailable"]}})]);expect(await screen.findByRole("alert")).toHaveTextContent("scanner_stale_or_unavailable");const status=screen.getByLabelText("Terminal status");expect(status).toHaveTextContent(/stale/i);expect(status).toHaveTextContent(/degraded/i);expect(status).toHaveTextContent("Connected")});
 it("renders disconnected state when no valid snapshot exists",async()=>{renderHome([new Response(null,{status:503})]);expect(await screen.findByRole("alert")).toHaveTextContent("backend disconnected");expect(screen.queryByText("$650.25")).not.toBeInTheDocument()});
 it("renders truthful empty positions and decision states",async()=>{renderHome([Response.json({...snapshot,active_trades:[],decisions:[]})]);expect(await screen.findByText("No active positions")).toBeInTheDocument();expect(screen.getByText("No recent decisions")).toBeInTheDocument()});
 it("uses the configured interval and applies polling updates without a reload",async()=>{
  vi.useFakeTimers({shouldAdvanceTime:true});
  renderHome([
    Response.json(snapshot),
    Response.json({...snapshot,snapshot_id:"changed-snapshot",symbols:{...snapshot.symbols,SPY:{...snapshot.symbols.SPY,scanner:{...snapshot.symbols.SPY.scanner,score:91}}}}),
  ]);
  expect(await screen.findByText(snapshot.snapshot_id,{exact:false})).toBeInTheDocument();
  await act(async()=>{await vi.advanceTimersByTimeAsync(SNAPSHOT_POLL_INTERVAL_MS+100)});
  expect(await screen.findByText("changed-snapshot",{exact:false})).toBeInTheDocument();
 });
 it("keeps the last valid snapshot visible during a transient polling failure",async()=>{
  renderHome([Response.json(snapshot),new Response(null,{status:503})]);
  expect(await screen.findByText(snapshot.snapshot_id,{exact:false})).toBeInTheDocument();
  screen.getByRole("button",{name:"Refresh"}).click();
  await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("Showing the last valid"));
  expect(screen.getByText("$650.25")).toBeInTheDocument();
 });
});
