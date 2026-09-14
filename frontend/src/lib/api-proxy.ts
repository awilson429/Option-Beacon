/**
 * Server-only FastAPI reverse proxy.
 * Do not import this module from Client Components; OPTIONBEACON_API_ORIGIN
 * must never appear in the browser bundle.
 */
import {logUpstreamUnreachable, nodeHttpFetch} from "@/lib/upstream-connect";

export type EnvLike = Record<string, string | undefined>;
export type UpstreamFetch = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export type UpstreamResolution =
  | {ok: true; origin: string}
  | {ok: false; status: number; error: string};

const REQUEST_HEADERS = ["accept", "last-event-id", "cache-control"] as const;
const RESPONSE_HEADERS = ["content-type", "cache-control", "connection", "x-accel-buffering"] as const;

export function resolveUpstreamOrigin(
  env: EnvLike = process.env,
  nodeEnv: string | undefined = env.NODE_ENV,
): UpstreamResolution {
  const raw = env.OPTIONBEACON_API_ORIGIN?.trim();
  if (raw) {
    const origin = raw.replace(/\/$/, "");
    if (!/^https?:\/\//i.test(origin)) {
      return {ok: false, status: 500, error: "OPTIONBEACON_API_ORIGIN must be an http(s) origin"};
    }
    return {ok: true, origin};
  }
  if (nodeEnv === "production") {
    return {ok: false, status: 503, error: "OPTIONBEACON_API_ORIGIN is not configured"};
  }
  return {ok: true, origin: "http://localhost:8000"};
}

export function buildUpstreamUrl(origin: string, path: string[], search = "") {
  const suffix = path.map(encodeURIComponent).join("/");
  return `${origin.replace(/\/$/, "")}/api/${suffix}${search}`;
}

export function pathIsSafe(path: string[]) {
  return path.length > 0 && path.every((segment) => segment.length > 0 && segment !== ".." && !segment.includes("/") && !segment.includes("\\"));
}

export function requestHeadersToForward(request: Request) {
  const headers = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const lastEventId = request.headers.get("Last-Event-ID") || request.headers.get("last-event-id");
  if (lastEventId) headers.set("Last-Event-ID", lastEventId);
  return headers;
}

export function responseHeadersToForward(upstream: Response) {
  const headers = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  const contentType = upstream.headers.get("content-type") || "";
  if (contentType.includes("text/event-stream")) {
    headers.set("Content-Type", contentType);
    headers.set("Cache-Control", "no-cache, no-transform");
    headers.set("Connection", "keep-alive");
    headers.set("X-Accel-Buffering", "no");
  } else if (!headers.has("cache-control")) {
    headers.set("Cache-Control", "no-store");
  }
  return headers;
}

export async function proxyOptionBeaconApi(
  request: Request,
  path: string[],
  env: EnvLike = process.env,
  fetchImpl: UpstreamFetch = nodeHttpFetch,
) {
  if (!pathIsSafe(path)) {
    return Response.json({detail: "Invalid API path"}, {status: 400, headers: {"Cache-Control": "no-store"}});
  }
  const resolved = resolveUpstreamOrigin(env);
  if (!resolved.ok) {
    console.error("api.proxy.unconfigured status=%s", resolved.status);
    return Response.json({detail: resolved.error}, {status: resolved.status, headers: {"Cache-Control": "no-store"}});
  }
  const target = buildUpstreamUrl(resolved.origin, path, new URL(request.url).search);
  let upstream: Response;
  try {
    upstream = await fetchImpl(target, {
      method: "GET",
      headers: requestHeadersToForward(request),
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });
  } catch (error) {
    await logUpstreamUnreachable(target, error);
    return Response.json({detail: "FastAPI upstream is unreachable"}, {status: 502, headers: {"Cache-Control": "no-store"}});
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeadersToForward(upstream),
  });
}
