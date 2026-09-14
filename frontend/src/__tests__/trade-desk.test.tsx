import {act,cleanup,render,screen,waitFor,within} from "@testing-library/react";
import {SWRConfig} from "swr";
import {afterEach,describe,expect,it,vi} from "vitest";
import Home from "@/app/page";
import {SNAPSHOT_POLL_INTERVAL_MS} from "@/hooks/use-options-data";
import {isAuthoritativeStale} from "@/components/trade-desk";
import {snapshot,system} from "./live-snapshot-fixture";

vi.mock("next/navigation",()=>({usePathname:()=>"/"}));
function renderHome(responses:(Response|Promise<Response>)[]=[Response.json(snapshot)]){
 let index=0;
 vi.stubGlobal("fetch",vi.fn(async(input:string|URL|Request)=>{const path=String(input);if(path.endsWith("/api/system/status"))return Response.json(system);if(path.endsWith("/api/live/snapshot"))return responses[Math.min(index++,responses.length-1)];throw new Error(path)}));
 return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><Home/></SWRConfig>);
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.useRealTimers()});

const staleSnapshot={...snapshot,market:{...snapshot.market,freshness:"stale"},scanner:{...snapshot.scanner,status:"STALE"},system:{...snapshot.system,state:{...system,worker_status:"degraded"},stale_or_missing:["scanner_stale_or_unavailable"]}};
const inProgressRefreshingSnapshot={
  ...snapshot,
  market:{...snapshot.market,freshness:"refreshing"},
  scanner:{
    ...snapshot.scanner,
    status:"SCANNING",
    cycle_completion_state:"SCANNING",
    last_successful_completed_cycle:"2026-09-14T17:15:00Z",
    health:{...snapshot.scanner.health,state:"SCANNING",worker_status:"running",data_freshness:"refreshing",last_success_at:"2026-09-14T17:15:00Z"},
  },
  symbols:{
    ...snapshot.symbols,
    SPY:{...snapshot.symbols.SPY,scanner:{...snapshot.symbols.SPY.scanner,freshness:"refreshing"}},
    QQQ:{...snapshot.symbols.QQQ,scanner:{...snapshot.symbols.QQQ.scanner,freshness:"refreshing"}},
  },
  system:{...snapshot.system,state:{...system,worker_status:"running",data_freshness:"refreshing"},stale_or_missing:[]},
};

describe("primary trading terminal",()=>{
 it("renders a healthy current snapshot with live TAKE treatment",async()=>{
  renderHome();
  expect(await screen.findByRole("heading",{name:"Market Command"})).toBeInTheDocument();
  expect(screen.getByRole("link",{name:"Market Command"})).toHaveAttribute("href","/");
  expect(screen.queryByText(/Data fresh/i)).not.toBeInTheDocument();
  const status=screen.getByLabelText("Terminal status");
  expect(status).toHaveTextContent("Connected");
  expect(status).toHaveTextContent("Open");
  expect(status).toHaveTextContent("Current");
  expect(status).toHaveTextContent("Healthy");
  const spy=screen.getByTestId("setup-SPY");
  expect(spy).toHaveAttribute("data-signal","live-take");
  expect(within(spy).getByText("TAKE")).toBeInTheDocument();
  expect(within(spy).queryByText("STALE DATA")).not.toBeInTheDocument();
  expect(within(spy).getByText(/Current/)).toBeInTheDocument();
  expect(within(spy).queryByText(/fresh/i)).not.toBeInTheDocument();
  expect(within(screen.getByTestId("setup-QQQ")).getByText("REJECTED")).toBeInTheDocument();
  expect(screen.getByText("EMA 9")).toBeInTheDocument();
  expect(screen.getAllByText("ALL RISK CONTROLS PASSED").length).toBeGreaterThan(0);
  const positions=screen.getByRole("region",{name:"Active positions"});
  expect(within(positions).getByText("SPY")).toBeInTheDocument();
  expect(within(positions).getByText("CALL")).toBeInTheDocument();
  expect(within(positions).getByText("HOLD")).toBeInTheDocument();
  expect(within(positions).getByText("$30.00")).toBeInTheDocument();
  expect(screen.queryByText("trade-1")).not.toBeInTheDocument();
  expect(screen.queryByText(/MANAGEMENT/i)).not.toBeInTheDocument();
  expect(screen.getByRole("heading",{name:"Recent trades"})).toBeInTheDocument();
  expect(screen.getByRole("heading",{name:"System & provenance"})).toBeInTheDocument();
  expect(screen.getByRole("link",{name:"Diagnostics"})).toHaveAttribute("href","/diagnostics/live-snapshot");
 });

 it("shows null numbers as unavailable and never as zero",async()=>{
  renderHome();
  const qqq=await screen.findByTestId("setup-QQQ");
  expect(within(qqq).getAllByText("Unavailable").length).toBeGreaterThan(0);
  expect(within(qqq).queryByText("$0.00")).not.toBeInTheDocument();
 });

 it("shows refreshing, not Current or STALE DATA, for a healthy long-running scan",async()=>{
  expect(isAuthoritativeStale(inProgressRefreshingSnapshot)).toBe(false);
  renderHome([Response.json(inProgressRefreshingSnapshot)]);
  const status=await screen.findByLabelText("Terminal status");
  expect(status).toHaveTextContent("Refreshing");
  expect(status).toHaveTextContent("Scanning");
  expect(status).not.toHaveTextContent("Current");
  expect(status).not.toHaveTextContent("Stale");
  expect(screen.getByRole("status")).toHaveTextContent(/actively refreshing/i);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(within(screen.getByTestId("setup-SPY")).queryByText("STALE DATA")).not.toBeInTheDocument();
  expect(within(screen.getByTestId("setup-SPY")).getByText(/Refreshing/)).toBeInTheDocument();
 });

 it("demotes a stale TAKE without changing it into WAIT or REJECTED and SSE does not override that",async()=>{
  renderHome([Response.json(staleSnapshot)]);
  const alert=await screen.findByRole("alert");
  expect(alert).toHaveTextContent("scanner_stale_or_unavailable");
  expect(alert).toHaveTextContent(/stale/i);
  expect(alert).toHaveTextContent(/historical/i);
  expect(screen.queryByText(/backend disconnected/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/Data fresh/i)).not.toBeInTheDocument();
  const status=screen.getByLabelText("Terminal status");
  expect(status).toHaveTextContent("Connected");
  expect(status).toHaveTextContent("Stale");
  expect(status).not.toHaveTextContent("Healthy");
  expect(status).not.toHaveTextContent("Current");
  const spy=screen.getByTestId("setup-SPY");
  expect(within(spy).getByText("TAKE")).toBeInTheDocument();
  expect(within(spy).getByText("STALE DATA")).toBeInTheDocument();
  expect(spy).toHaveAttribute("data-signal","stale-take");
  expect(within(spy).getByText(/Stale/)).toBeInTheDocument();
  expect(within(spy).queryByText(/fresh/i)).not.toBeInTheDocument();
  expect(within(spy).queryByText("WAIT")).not.toBeInTheDocument();
  expect(within(spy).queryByText("REJECTED")).not.toBeInTheDocument();
 });

 it("renders disconnected state when no valid snapshot exists",async()=>{
  renderHome([new Response(null,{status:503})]);
  expect(await screen.findByRole("alert")).toHaveTextContent("backend disconnected");
  expect(screen.queryByText("$650.25")).not.toBeInTheDocument();
 });

 it("keeps last valid values when the API disconnects after a healthy snapshot",async()=>{
  renderHome([Response.json(snapshot),new Response(null,{status:503})]);
  expect(await screen.findByTestId("setup-SPY")).toHaveAttribute("data-signal","live-take");
  screen.getByRole("button",{name:"Refresh"}).click();
  await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("Showing the last valid"));
  expect(screen.getByRole("alert")).toHaveTextContent(/disconnected/i);
  expect(screen.getByRole("alert")).not.toHaveTextContent(/Authoritative data is stale/i);
  expect(screen.getByLabelText("Terminal status")).toHaveTextContent("Disconnected");
  expect(screen.getByText("$650.25")).toBeInTheDocument();
  expect(screen.getByTestId("setup-SPY")).toHaveAttribute("data-signal","live-take");
 });

 it("renders truthful empty positions and decision states",async()=>{
  renderHome([Response.json({...snapshot,active_trades:[],decisions:[]})]);
  expect(await screen.findByText("No active positions")).toBeInTheDocument();
  expect(screen.getByText("No recent decisions")).toBeInTheDocument();
 });

 it("keeps direction, action, and score visible in decision and trade rows",async()=>{
  renderHome();
  const decisions=await screen.findByRole("region",{name:"Decisions"});
  expect(decisions).toHaveTextContent("SPY");
  expect(decisions).toHaveTextContent("TAKE");
  expect(decisions).toHaveTextContent("CALL");
  expect(decisions).toHaveTextContent("84");
  const trades=screen.getByRole("region",{name:"Recent trades"});
  expect(trades).toHaveTextContent("QQQ");
  expect(trades).toHaveTextContent("PUT");
  expect(trades).toHaveTextContent("TARGET");
 });

 it("uses the configured interval and applies polling updates without a reload",async()=>{
  vi.useFakeTimers({shouldAdvanceTime:true});
  renderHome([
    Response.json(snapshot),
    Response.json({...snapshot,snapshot_id:"changed-snapshot",symbols:{...snapshot.symbols,SPY:{...snapshot.symbols.SPY,scanner:{...snapshot.symbols.SPY.scanner,score:91}}}}),
  ]);
  expect((await screen.findAllByText(snapshot.snapshot_id,{exact:false})).length).toBeGreaterThan(0);
  await act(async()=>{await vi.advanceTimersByTimeAsync(SNAPSHOT_POLL_INTERVAL_MS+100)});
  expect(screen.getAllByText("changed-snapshot",{exact:false}).length).toBeGreaterThan(0);
 });

 it("keeps the last valid snapshot visible during a transient polling failure",async()=>{
  renderHome([Response.json(snapshot),new Response(null,{status:503})]);
  expect((await screen.findAllByText(snapshot.snapshot_id,{exact:false})).length).toBeGreaterThan(0);
  screen.getByRole("button",{name:"Refresh"}).click();
  await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("Showing the last valid"));
  expect(screen.getByText("$650.25")).toBeInTheDocument();
 });
});
