import {cleanup,render,screen,within} from "@testing-library/react";
import {SWRConfig} from "swr";
import {afterEach,describe,expect,it,vi} from "vitest";
import LiveSnapshotPage from "@/app/diagnostics/live-snapshot/page";
import type {LiveSnapshot} from "@/lib/types";
import {snapshot,system} from "./live-snapshot-fixture";

vi.mock("next/navigation",()=>({usePathname:()=>"/diagnostics/live-snapshot"}));

const unavailableQqq:LiveSnapshot={
  ...snapshot,
  symbols:{
    ...snapshot.symbols,
    QQQ:{
      symbol:"QQQ",
      data_status:"unavailable",
      observation:null,
      scanner:{...snapshot.symbols.QQQ.scanner,data_status:"unavailable",underlying_price:null,score:null,setup:null},
      latest_decisions:[],
    },
  },
};

function show(payload:LiveSnapshot=snapshot,mode:"ok"|"pending"|"error"="ok"){
  vi.stubGlobal("fetch",vi.fn(async(input:string|URL|Request)=>{
    const path=String(input);
    if(path.endsWith("/api/system/status")) return Response.json(system);
    if(path.endsWith("/api/live/snapshot")){
      if(mode==="pending") return new Promise<Response>(()=>{});
      if(mode==="error") return new Response(null,{status:503});
      return Response.json(payload);
    }
    throw new Error(path);
  }));
  return render(<SWRConfig value={{provider:()=>new Map(),dedupingInterval:0}}><LiveSnapshotPage/></SWRConfig>);
}

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

describe("live snapshot diagnostics",()=>{
  it("renders connection, symbols, cycle and decisions",async()=>{
    show();
    expect(await screen.findByRole("heading",{name:"Canonical Live Snapshot"})).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(within(screen.getByTestId("snapshot-SPY")).getByText("650.25")).toBeInTheDocument();
    expect(screen.getByText("cycle-42")).toBeInTheDocument();
    expect(screen.getAllByText("ALL_RISK_CONTROLS_PASSED").length).toBeGreaterThan(0);
  });

  it("shows loading state",()=>{
    show(snapshot,"pending");
    expect(screen.getByLabelText("Loading live snapshot")).toBeInTheDocument();
  });

  it("shows backend unavailable state",async()=>{
    show(snapshot,"error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable");
  });

  it("renders null values as unavailable rather than zero",async()=>{
    show(unavailableQqq);
    const qqq=await screen.findByTestId("snapshot-QQQ");
    expect(within(qqq).getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(within(qqq).getByText(/no value was inferred/i)).toBeInTheDocument();
    expect(within(qqq).queryByText("0")).not.toBeInTheDocument();
    expect(within(qqq).queryByText("0.00")).not.toBeInTheDocument();
  });
});
