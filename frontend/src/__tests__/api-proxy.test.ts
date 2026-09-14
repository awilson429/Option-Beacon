import {readFileSync} from "node:fs";
import {describe, expect, it, vi} from "vitest";
import {resolveApiBaseUrl, endpoints} from "@/lib/api";
import {
  buildUpstreamUrl,
  pathIsSafe,
  proxyOptionBeaconApi,
  resolveUpstreamOrigin,
} from "@/lib/api-proxy";

describe("browser API base URL", () => {
  it("uses localhost in development and same-origin in production", () => {
    expect(resolveApiBaseUrl(undefined, "development")).toBe("http://localhost:8000");
    expect(resolveApiBaseUrl(undefined, "test")).toBe("http://localhost:8000");
    expect(resolveApiBaseUrl(undefined, "production")).toBe("");
    expect(resolveApiBaseUrl("", "production")).toBe("");
    expect(resolveApiBaseUrl("https://api.example.com/", "production")).toBe("https://api.example.com");
  });

  it("keeps EventSource and REST on same-origin /api paths in production", () => {
    const base = resolveApiBaseUrl(undefined, "production");
    expect(`${base}${endpoints.liveSnapshot}`).toBe("/api/live/snapshot");
    expect(`${base}${endpoints.liveEvents}`).toBe("/api/live/events");
    expect(`${base}${endpoints.system}`).toBe("/api/system/status");
  });

  it("does not leak the private FastAPI origin into client configuration", () => {
    const client = ["src/lib/api.ts", "src/hooks/use-live-events.ts", "src/hooks/use-options-data.ts"]
      .map((file) => readFileSync(file, "utf8")).join("\n");
    expect(client).not.toMatch(/OPTIONBEACON_API_ORIGIN/);
    expect(client).not.toMatch(/RAILWAY_PRIVATE_DOMAIN/);
    expect(client).not.toMatch(/railway\.internal/);
  });
});

describe("server-side FastAPI upstream", () => {
  it("uses OPTIONBEACON_API_ORIGIN and never falls back to localhost in production", () => {
    expect(resolveUpstreamOrigin({OPTIONBEACON_API_ORIGIN: "http://api.railway.internal:8000/"}, "production"))
      .toEqual({ok: true, origin: "http://api.railway.internal:8000"});
    expect(resolveUpstreamOrigin({}, "production")).toEqual({
      ok: false, status: 503, error: "OPTIONBEACON_API_ORIGIN is not configured",
    });
    expect(resolveUpstreamOrigin({OPTIONBEACON_API_ORIGIN: "api.railway.internal"}, "production").ok).toBe(false);
    expect(resolveUpstreamOrigin({}, "development")).toEqual({ok: true, origin: "http://localhost:8000"});
  });

  it("constructs the private /api path with query string", () => {
    expect(buildUpstreamUrl("http://api.railway.internal:8080", ["live", "snapshot"], "")).toBe(
      "http://api.railway.internal:8080/api/live/snapshot",
    );
    expect(buildUpstreamUrl("http://api.railway.internal:8080", ["trades", "recent"], "?limit=12")).toBe(
      "http://api.railway.internal:8080/api/trades/recent?limit=12",
    );
    expect(pathIsSafe(["live", "events"])).toBe(true);
    expect(pathIsSafe(["..", "secret"])).toBe(false);
  });

  it("forwards Last-Event-ID and preserves SSE stream headers without buffering the body", async () => {
    const chunks: string[] = [];
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(": heartbeat\n\n"));
        controller.enqueue(new TextEncoder().encode("event: snapshot.changed\ndata: {}\n\n"));
        controller.close();
      },
    });
    const fetchImpl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      expect(String(input)).toBe("http://api.railway.internal:8000/api/live/events");
      const headers = new Headers(init?.headers);
      expect(headers.get("Last-Event-ID")).toBe("snap:4");
      expect(headers.get("accept")).toBe("text/event-stream");
      return new Response(body, {
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          "X-Accel-Buffering": "no",
        },
      });
    });
    const request = new Request("http://localhost:3000/api/live/events", {
      headers: {"Accept": "text/event-stream", "Last-Event-ID": "snap:4"},
    });
    const response = await proxyOptionBeaconApi(
      request, ["live", "events"],
      {OPTIONBEACON_API_ORIGIN: "http://api.railway.internal:8000", NODE_ENV: "production"},
      fetchImpl,
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    expect(response.headers.get("cache-control")).toContain("no-cache");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(response.body).not.toBeNull();
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      chunks.push(decoder.decode(value));
    }
    expect(chunks.join("")).toContain(": heartbeat");
    expect(chunks.join("")).toContain("snapshot.changed");
  });

  it("logs hostname, port, and error fields when the upstream connect fails", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchImpl = vi.fn(async () => {
      throw Object.assign(new Error("fetch failed"), {
        name: "TypeError",
        cause: {name: "ConnectTimeoutError", code: "UND_ERR_CONNECT_TIMEOUT", message: "Connect Timeout Error"},
      });
    });
    const response = await proxyOptionBeaconApi(
      new Request("http://localhost:3000/api/health"),
      ["health"],
      {OPTIONBEACON_API_ORIGIN: "http://api.railway.internal:8080", NODE_ENV: "production"},
      fetchImpl,
    );
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({detail: "FastAPI upstream is unreachable"});
    const line = spy.mock.calls.map((call) => call.map(String).join(" ")).join("\n");
    expect(line).toContain("api.proxy.upstream_unreachable");
    expect(line).toContain("hostname=api.railway.internal");
    expect(line).toContain("port=8080");
    expect(line).toContain("errorName=TypeError");
    expect(line).toContain("causeCode=UND_ERR_CONNECT_TIMEOUT");
    expect(line).not.toContain("DATABASE_URL");
    spy.mockRestore();
  });

  it("fails closed when production origin is missing and does not call localhost", async () => {
    const fetchImpl = vi.fn();
    const response = await proxyOptionBeaconApi(
      new Request("http://localhost:3000/api/live/snapshot"),
      ["live", "snapshot"],
      {NODE_ENV: "production"},
      fetchImpl,
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({detail: "OPTIONBEACON_API_ORIGIN is not configured"});
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
