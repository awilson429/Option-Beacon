import http from "node:http";
import {afterEach, describe, expect, it, vi} from "vitest";
import {
  formatResolvedAddresses,
  logUpstreamUnreachable,
  nodeHttpFetch,
  orderPrivateNetworkAddresses,
  parseUpstreamTarget,
  sanitizeLogText,
  selectLookupResult,
  summarizeUpstreamError,
} from "@/lib/upstream-connect";

describe("Railway private DNS ordering", () => {
  it("prefers IPv6 for railway.internal and IPv4 for localhost", () => {
    const mixed = [
      {address: "10.1.2.3", family: 4},
      {address: "fd12::abcd", family: 6},
    ];
    expect(orderPrivateNetworkAddresses("api.railway.internal", mixed)).toEqual([
      {address: "fd12::abcd", family: 6},
      {address: "10.1.2.3", family: 4},
    ]);
    expect(orderPrivateNetworkAddresses("localhost", mixed)).toEqual([
      {address: "10.1.2.3", family: 4},
      {address: "fd12::abcd", family: 6},
    ]);
  });

  it("parses hostname and port without userinfo", () => {
    expect(parseUpstreamTarget("http://api.railway.internal:8080/api/health")).toEqual({
      hostname: "api.railway.internal",
      port: "8080",
    });
    expect(parseUpstreamTarget("http://user:secret@api.railway.internal:8080/api/health")).toEqual({
      hostname: "api.railway.internal",
      port: "8080",
    });
  });
});

describe("lookupPreferIpv6", () => {
  it("returns IPv6 first when all addresses are requested", () => {
    const selected = selectLookupResult(
      "api.railway.internal",
      [
        {address: "10.8.0.2", family: 4},
        {address: "fd12::2", family: 6},
      ],
      {all: true, family: 0},
    );
    expect(selected.ok).toBe(true);
    if (selected.ok) {
      expect(selected.addresses[0]).toEqual({address: "fd12::2", family: 6});
    }
  });
});

describe("upstream failure logs", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("redacts database URLs and summarizes undici-style causes", () => {
    expect(sanitizeLogText("upstream postgres://user:hunter2@db.internal:5432/app failed")).toBe(
      "upstream [redacted-url] failed",
    );
    const error = Object.assign(new Error("fetch failed"), {
      name: "TypeError",
      code: undefined,
      cause: {
        name: "ConnectTimeoutError",
        code: "UND_ERR_CONNECT_TIMEOUT",
        message: "Connect Timeout Error",
      },
    });
    expect(summarizeUpstreamError(error)).toMatchObject({
      name: "TypeError",
      code: "UND_ERR_CONNECT_TIMEOUT",
      causeName: "ConnectTimeoutError",
      causeCode: "UND_ERR_CONNECT_TIMEOUT",
    });
  });

  it("logs hostname, port, DNS families, and error codes without secrets", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    await logUpstreamUnreachable(
      "http://api.railway.internal:8080/api/health?token=secret",
      Object.assign(new Error("fetch failed"), {
        name: "TypeError",
        cause: {name: "Error", code: "ENOTFOUND", message: "getaddrinfo ENOTFOUND api.railway.internal"},
      }),
      async () => [{address: "fd12::9", family: 6}],
    );
    const line = spy.mock.calls.map((call) => call.map(String).join(" ")).join("\n");
    expect(line).toContain("hostname=api.railway.internal");
    expect(line).toContain("port=8080");
    expect(line).toContain("dns=6=fd12::9");
    expect(line).toContain("errorName=TypeError");
    expect(line).toContain("causeCode=ENOTFOUND");
    expect(line).not.toContain("token=secret");
    expect(line).not.toContain("postgres://");
    expect(formatResolvedAddresses([{address: "fd12::9", family: 6}])).toBe("6=fd12::9");
  });
});

describe("nodeHttpFetch", () => {
  it("streams SSE bytes and forwards Last-Event-ID", async () => {
    const seen: string[] = [];
    const server = http.createServer((req, res) => {
      seen.push(`${req.method} ${req.url} ${req.headers["last-event-id"] || ""}`);
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
      });
      res.write(": heartbeat\n\n");
      res.write("event: snapshot.changed\ndata: {}\n\n");
      res.end();
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    try {
      const response = await nodeHttpFetch(`http://127.0.0.1:${port}/api/live/events`, {
        method: "GET",
        headers: {accept: "text/event-stream", "Last-Event-ID": "snap:4"},
      });
      expect(response.status).toBe(200);
      expect(response.headers.get("content-type")).toContain("text/event-stream");
      expect(await response.text()).toContain(": heartbeat");
      expect(seen[0]).toContain("GET /api/live/events snap:4");
    } finally {
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });
});
