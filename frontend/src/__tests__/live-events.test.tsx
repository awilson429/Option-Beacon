import {act,cleanup,render,screen,waitFor} from "@testing-library/react";
import {SWRConfig} from "swr";
import {afterEach,describe,expect,it,vi} from "vitest";
import Home from "@/app/page";
import {parseLiveEvent,shouldRefreshSnapshot,useLiveEvents} from "@/hooks/use-live-events";
import {SNAPSHOT_POLL_INTERVAL_MS,SNAPSHOT_SAFETY_POLL_INTERVAL_MS,scheduleCoalescedRefresh} from "@/hooks/use-options-data";
import {resolveApiBaseUrl} from "@/lib/api";
import {snapshot,system} from "./live-snapshot-fixture";

class FakeEventSource {
  static CONNECTING=0; static OPEN=1; static CLOSED=2;
  static instances:FakeEventSource[]=[];
  url:string; readyState=FakeEventSource.CONNECTING;
  onopen:((event:Event)=>void)|null=null;
  onerror:((event:Event)=>void)|null=null;
  onmessage:((event:MessageEvent<string>)=>void)|null=null;
  private listeners=new Map<string,Set<(event:MessageEvent<string>)=>void>>();
  constructor(url:string){this.url=url;FakeEventSource.instances.push(this)}
  addEventListener(type:string,fn:(event:MessageEvent<string>)=>void){
    const bucket=this.listeners.get(type)??new Set(); bucket.add(fn); this.listeners.set(type,bucket);
  }
  close(){this.readyState=FakeEventSource.CLOSED}
  open(){this.readyState=FakeEventSource.OPEN; this.onopen?.(new Event("open"))}
  emit(type:string,data:unknown,lastEventId=""){
    const event=new MessageEvent<string>(type,{data:typeof data==="string"?data:JSON.stringify(data),lastEventId});
    this.listeners.get(type)?.forEach(fn=>fn(event));
    if(type==="message") this.onmessage?.(event);
  }
  fail(closed=false){
    this.readyState=closed?FakeEventSource.CLOSED:FakeEventSource.CONNECTING;
    this.onerror?.(new Event("error"));
  }
}

const envelope=(overrides:Record<string,unknown>={})=>({
  event_id:"snap:1", event_type:"snapshot.changed", occurred_at:"2026-09-13T14:31:00Z",
  snapshot_id:"changed-snapshot", cycle_id:"cycle-42", entity_id:"changed-snapshot", schema_version:"1", ...overrides,
});

function renderHome(responses:(Response|Promise<Response>)[]=[Response.json(snapshot)]){
  let index=0;
  const fetchMock=vi.fn(async(input:string|URL|Request)=>{
    const path=String(input);
    if(path.endsWith("/api/system/status")) return Response.json(system);
    if(path.endsWith("/api/live/snapshot")) return responses[Math.min(index++,responses.length-1)];
    throw new Error(path);
  });
  vi.stubGlobal("fetch",fetchMock);
  vi.stubGlobal("EventSource",FakeEventSource);
  const view=render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><Home/></SWRConfig>);
  return {view,fetchMock};
}

afterEach(()=>{cleanup();FakeEventSource.instances.length=0;vi.unstubAllGlobals();vi.useRealTimers()});

describe("live event helpers",()=>{
  it("parses envelopes and ignores malformed payloads",()=>{
    expect(parseLiveEvent("{not json")).toBeNull();
    expect(parseLiveEvent(JSON.stringify({event_id:"1"}))).toBeNull();
    expect(parseLiveEvent(JSON.stringify(envelope()))?.event_type).toBe("snapshot.changed");
  });

  it("refreshes on resync or a different snapshot_id, not on unknown types",()=>{
    expect(shouldRefreshSnapshot(envelope({event_type:"resync.required",snapshot_id:snapshot.snapshot_id}),snapshot.snapshot_id)).toBe(true);
    expect(shouldRefreshSnapshot(envelope({snapshot_id:snapshot.snapshot_id}),snapshot.snapshot_id)).toBe(false);
    expect(shouldRefreshSnapshot(envelope({snapshot_id:"other"}),snapshot.snapshot_id)).toBe(true);
    expect(shouldRefreshSnapshot(envelope({event_type:"trade.opened"}),snapshot.snapshot_id)).toBe(false);
  });

  it("resolves production, same-origin, and development API bases",()=>{
    expect(resolveApiBaseUrl(undefined, "development")).toBe("http://localhost:8000");
    expect(resolveApiBaseUrl(undefined, "production")).toBe("");
    expect(resolveApiBaseUrl("")).toBe("");
    expect(resolveApiBaseUrl("https://api.example.com/")).toBe("https://api.example.com");
  });

  it("coalesces overlapping snapshot refreshes into one in-flight plus one trailing call",async()=>{
    const inflight={current:false};
    const queued={current:false};
    let started=0;
    let releaseFirst!:()=>void;
    const first=new Promise<void>(resolve=>{releaseFirst=resolve});
    const revalidate=vi.fn(()=>{
      started+=1;
      return started===1 ? first : Promise.resolve();
    });
    scheduleCoalescedRefresh(inflight,queued,revalidate);
    scheduleCoalescedRefresh(inflight,queued,revalidate);
    scheduleCoalescedRefresh(inflight,queued,revalidate);
    expect(revalidate).toHaveBeenCalledTimes(1);
    releaseFirst();
    await first;
    await waitFor(()=>expect(revalidate).toHaveBeenCalledTimes(2));
  });
});

describe("Market Command SSE client",()=>{
  it("connects EventSource and revalidates the canonical snapshot on snapshot.changed",async()=>{
    const changed={...snapshot,snapshot_id:"changed-snapshot",symbols:{...snapshot.symbols,SPY:{...snapshot.symbols.SPY,scanner:{...snapshot.symbols.SPY.scanner,score:91}}}};
    const {fetchMock}=renderHome([Response.json(snapshot),Response.json(changed)]);
    expect(await screen.findByRole("heading",{name:"Market Command"})).toBeInTheDocument();
    await waitFor(()=>expect(FakeEventSource.instances[0]?.url).toMatch(/\/api\/live\/events$/));
    act(()=>FakeEventSource.instances[0].open());
    expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot"))).toHaveLength(1);
    act(()=>FakeEventSource.instances[0].emit("snapshot.changed",envelope()));
    await waitFor(()=>expect(screen.getAllByText("changed-snapshot",{exact:false}).length).toBeGreaterThan(0));
    expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot")).length).toBeGreaterThan(1);
  });

  it("does not storm fetches when a duplicate event_id arrives",async()=>{
    const {fetchMock}=renderHome([Response.json(snapshot),Response.json({...snapshot,snapshot_id:"changed-snapshot"})]);
    await screen.findByRole("heading",{name:"Market Command"});
    act(()=>{FakeEventSource.instances[0].open(); FakeEventSource.instances[0].emit("snapshot.changed",envelope())});
    await waitFor(()=>expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot")).length).toBe(2));
    act(()=>FakeEventSource.instances[0].emit("snapshot.changed",envelope()));
    await new Promise(resolve=>setTimeout(resolve,30));
    expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot")).length).toBe(2);
  });

  it("keeps the last snapshot visible and resumes polling when SSE drops",async()=>{
    vi.useFakeTimers({shouldAdvanceTime:true});
    const {fetchMock}=renderHome([
      Response.json(snapshot),
      Response.json({...snapshot,snapshot_id:"poll-fallback"}),
    ]);
    expect(await screen.findByText("$650.25")).toBeInTheDocument();
    act(()=>FakeEventSource.instances[0].open());
    act(()=>FakeEventSource.instances[0].fail());
    await act(async()=>{await vi.advanceTimersByTimeAsync(SNAPSHOT_POLL_INTERVAL_MS+100)});
    expect(screen.getByText("$650.25")).toBeInTheDocument();
    await waitFor(()=>expect(screen.getAllByText("poll-fallback",{exact:false}).length).toBeGreaterThan(0));
    expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot")).length).toBeGreaterThan(1);
  });

  it("ignores unknown event types and still honors resync.required",async()=>{
    const {fetchMock}=renderHome([Response.json(snapshot),Response.json({...snapshot,snapshot_id:"resync-snapshot"})]);
    await screen.findByRole("heading",{name:"Market Command"});
    act(()=>{
      FakeEventSource.instances[0].open();
      FakeEventSource.instances[0].emit("message",envelope({event_type:"trade.opened",event_id:"unknown:1"}));
    });
    await new Promise(resolve=>setTimeout(resolve,30));
    expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot"))).toHaveLength(1);
    act(()=>FakeEventSource.instances[0].emit("resync.required",envelope({event_type:"resync.required",event_id:"resync:1",snapshot_id:snapshot.snapshot_id})));
    await waitFor(()=>expect(screen.getAllByText("resync-snapshot",{exact:false}).length).toBeGreaterThan(0));
  });

  it("reconnects after a closed EventSource and resyncs the snapshot",async()=>{
    vi.useFakeTimers({shouldAdvanceTime:true});
    const {fetchMock}=renderHome([
      Response.json(snapshot),
      Response.json({...snapshot,snapshot_id:"reconnect-snapshot"}),
    ]);
    await screen.findByRole("heading",{name:"Market Command"});
    act(()=>{FakeEventSource.instances[0].open(); FakeEventSource.instances[0].fail(true)});
    await act(async()=>{await vi.advanceTimersByTimeAsync(2_000)});
    expect(FakeEventSource.instances[0].readyState).toBe(FakeEventSource.CLOSED);
    expect(FakeEventSource.instances).toHaveLength(2);
    act(()=>{
      FakeEventSource.instances[1].open();
      FakeEventSource.instances[1].emit("resync.required",envelope({event_type:"resync.required",event_id:"reconnect:1"}));
    });
    await waitFor(()=>expect(screen.getAllByText("reconnect-snapshot",{exact:false}).length).toBeGreaterThan(0));
    expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot")).length).toBeGreaterThan(1);
  });

  it("closes EventSource on unmount",async()=>{
    function Probe(){useLiveEvents();return <p>probe</p>}
    vi.stubGlobal("EventSource",FakeEventSource);
    const view=render(<Probe/>);
    await waitFor(()=>expect(FakeEventSource.instances).toHaveLength(1));
    view.unmount();
    expect(FakeEventSource.instances[0].readyState).toBe(FakeEventSource.CLOSED);
  });

  it("keeps manual Refresh working while SSE is open",async()=>{
    const {fetchMock}=renderHome([Response.json(snapshot),Response.json({...snapshot,snapshot_id:"manual-refresh"})]);
    await screen.findByRole("heading",{name:"Market Command"});
    act(()=>FakeEventSource.instances[0].open());
    screen.getByRole("button",{name:"Refresh"}).click();
    await waitFor(()=>expect(screen.getAllByText("manual-refresh",{exact:false}).length).toBeGreaterThan(0));
    expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot")).length).toBeGreaterThan(1);
  });

  it("does not treat a dropped SSE connection as stale TAKE",async()=>{
    renderHome();
    const spy=await screen.findByTestId("setup-SPY");
    expect(spy).toHaveAttribute("data-signal","live-take");
    act(()=>{FakeEventSource.instances[0].open(); FakeEventSource.instances[0].fail()});
    expect(screen.getByTestId("setup-SPY")).toHaveAttribute("data-signal","live-take");
    expect(screen.queryByText("STALE DATA")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Terminal status")).toHaveTextContent("Connected");
    expect(screen.getByLabelText("Terminal status")).toHaveTextContent("Current");
  });

  it("uses the slower safety poll only while SSE is open",async()=>{
    vi.useFakeTimers({shouldAdvanceTime:true});
    const {fetchMock}=renderHome([
      Response.json(snapshot),
      Response.json({...snapshot,snapshot_id:"safety-poll"}),
    ]);
    await screen.findByRole("heading",{name:"Market Command"});
    act(()=>FakeEventSource.instances[0].open());
    await act(async()=>{await vi.advanceTimersByTimeAsync(SNAPSHOT_POLL_INTERVAL_MS+100)});
    expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/api/live/snapshot"))).toHaveLength(1);
    await act(async()=>{await vi.advanceTimersByTimeAsync(SNAPSHOT_SAFETY_POLL_INTERVAL_MS)});
    await waitFor(()=>expect(screen.getAllByText("safety-poll",{exact:false}).length).toBeGreaterThan(0));
  });
});
