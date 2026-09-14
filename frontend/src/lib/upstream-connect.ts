/**
 * Server-only upstream connector for Railway private DNS.
 * Do not import from Client Components.
 *
 * Node's global fetch (undici) is a poor fit for legacy Railway private
 * networking: DNS is often AAAA-only, Node defaults to ipv4first, and the
 * frozen undici Agent does not reliably Happy-Eyeball onto IPv6. Node's
 * http.request honors family: 0 and a custom dns.lookup.
 */
import {lookup as dnsLookup} from "node:dns";
import http from "node:http";
import https from "node:https";
import type {IncomingMessage, RequestOptions} from "node:http";
import type {LookupAddress} from "node:dns";
import type {LookupFunction} from "node:net";
import {Readable} from "node:stream";

export type ResolvedAddress = {address: string; family: number};

const REDACT_URLS = /(?:postgres(?:ql)?|mysql|mongodb|redis|amqp|https?):\/\/[^\s]+/gi;

export function parseUpstreamTarget(url: string): {hostname: string; port: string} {
  const parsed = new URL(url);
  const port = parsed.port || (parsed.protocol === "https:" ? "443" : "80");
  return {hostname: parsed.hostname, port};
}

export function orderPrivateNetworkAddresses(hostname: string, addresses: ResolvedAddress[]): ResolvedAddress[] {
  const v6 = addresses.filter((entry) => entry.family === 6);
  const v4 = addresses.filter((entry) => entry.family === 4);
  const isLoopback =
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname === "127.0.0.1" ||
    hostname === "::1";
  if (isLoopback) return [...v4, ...v6];
  return v6.length > 0 ? [...v6, ...v4] : [...v4];
}

export function lookupAllAddresses(hostname: string): Promise<ResolvedAddress[]> {
  return new Promise((resolve, reject) => {
    dnsLookup(hostname, {all: true, verbatim: true}, (error, addresses) => {
      if (error) reject(error);
      else resolve(addresses);
    });
  });
}

export function selectLookupResult(
  hostname: string,
  addresses: ResolvedAddress[],
  options: {family?: number; all?: boolean} = {},
): {ok: true; addresses: ResolvedAddress[]} | {ok: false; error: NodeJS.ErrnoException} {
  let resolved = orderPrivateNetworkAddresses(hostname, addresses);
  if (options.family === 4 || options.family === 6) {
    resolved = resolved.filter((entry) => entry.family === options.family);
  }
  if (resolved.length === 0) {
    const notFound = Object.assign(new Error(`getaddrinfo ENOTFOUND ${hostname}`), {
      code: "ENOTFOUND",
      hostname,
    }) as NodeJS.ErrnoException;
    return {ok: false, error: notFound};
  }
  return {ok: true, addresses: resolved};
}

export const lookupPreferIpv6: LookupFunction = (hostname, options, callback) => {
  dnsLookup(hostname, {all: true, verbatim: true}, (error, addresses) => {
    if (error) {
      callback(error, "", 0);
      return;
    }
    const family = typeof options === "object" && typeof options.family === "number" ? options.family : undefined;
    const wantAll = typeof options === "object" && options.all === true;
    const selected = selectLookupResult(hostname, addresses as LookupAddress[], {family, all: wantAll});
    if (!selected.ok) {
      callback(selected.error, "", 0);
      return;
    }
    if (wantAll) {
      callback(null, selected.addresses);
      return;
    }
    callback(null, selected.addresses[0].address, selected.addresses[0].family);
  });
};

export function sanitizeLogText(value: string): string {
  return value.replace(REDACT_URLS, "[redacted-url]");
}

function errorFields(error: unknown): {name: string; code: string; message: string} {
  const err = error as {name?: string; code?: string; message?: string; cause?: unknown} | undefined;
  const cause = err?.cause as {name?: string; code?: string; message?: string} | undefined;
  const nested = Array.isArray((error as {errors?: unknown[]})?.errors)
    ? ((error as {errors: unknown[]}).errors)[0]
    : undefined;
  const nestedFields = nested && nested !== error ? errorFields(nested) : undefined;
  return {
    name: err?.name || nestedFields?.name || "Error",
    code: String(err?.code || cause?.code || nestedFields?.code || ""),
    message: sanitizeLogText(String(err?.message || cause?.message || nestedFields?.message || "")),
  };
}

export function summarizeUpstreamError(error: unknown): {
  name: string;
  code: string;
  message: string;
  causeName: string;
  causeCode: string;
  causeMessage: string;
} {
  const fields = errorFields(error);
  const cause = (error as {cause?: unknown})?.cause;
  const causeFields = cause ? errorFields(cause) : {name: "", code: "", message: ""};
  return {
    name: fields.name,
    code: fields.code,
    message: fields.message,
    causeName: causeFields.name,
    causeCode: causeFields.code,
    causeMessage: causeFields.message,
  };
}

export function formatResolvedAddresses(addresses: ResolvedAddress[]): string {
  if (addresses.length === 0) return "none";
  return addresses.map((entry) => `${entry.family}=${entry.address}`).join(",");
}

export async function logUpstreamUnreachable(
  target: string,
  error: unknown,
  lookupAll: (hostname: string) => Promise<ResolvedAddress[]> = lookupAllAddresses,
): Promise<void> {
  let hostname = "invalid";
  let port = "";
  try {
    ({hostname, port} = parseUpstreamTarget(target));
  } catch {
    hostname = "invalid";
  }
  let dns = "unresolved";
  try {
    dns = formatResolvedAddresses(orderPrivateNetworkAddresses(hostname, await lookupAll(hostname)));
  } catch (dnsError) {
    const fields = summarizeUpstreamError(dnsError);
    dns = `error:${fields.code || fields.name}`;
  }
  const fields = summarizeUpstreamError(error);
  console.error(
    [
      "api.proxy.upstream_unreachable",
      `hostname=${hostname}`,
      `port=${port}`,
      `dns=${dns}`,
      `errorName=${fields.name}`,
      `errorCode=${fields.code || "-"}`,
      `causeName=${fields.causeName || "-"}`,
      `causeCode=${fields.causeCode || "-"}`,
      `causeMessage=${fields.causeMessage || fields.message || "-"}`,
    ].join(" "),
  );
}

function incomingToHeaders(res: IncomingMessage): Headers {
  const headers = new Headers();
  for (const [key, value] of Object.entries(res.headers)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      for (const item of value) headers.append(key, item);
    } else {
      headers.set(key, value);
    }
  }
  return headers;
}

export async function nodeHttpFetch(input: string | URL | Request, init: RequestInit = {}): Promise<Response> {
  const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
  const parsed = new URL(url);
  const isHttps = parsed.protocol === "https:";
  const request = isHttps ? https.request : http.request;
  const headers = new Headers(init.headers);
  if (typeof input !== "string" && !(input instanceof URL)) {
    input.headers.forEach((value, key) => {
      if (!headers.has(key)) headers.set(key, value);
    });
  }
  const requestHeaders: Record<string, string> = {};
  headers.forEach((value, key) => {
    requestHeaders[key] = value;
  });
  const options: RequestOptions = {
    protocol: parsed.protocol,
    hostname: parsed.hostname,
    port: parsed.port || (isHttps ? 443 : 80),
    path: `${parsed.pathname}${parsed.search}`,
    method: init.method || "GET",
    headers: requestHeaders,
    family: 0,
    lookup: lookupPreferIpv6,
    signal: init.signal ?? undefined,
  };
  return new Promise((resolve, reject) => {
    const req = request({
      ...options,
      autoSelectFamily: true,
      autoSelectFamilyAttemptTimeout: 250,
    } as RequestOptions, (res) => {
      const body = Readable.toWeb(res) as ReadableStream<Uint8Array>;
      resolve(new Response(body, {
        status: res.statusCode || 502,
        statusText: res.statusMessage,
        headers: incomingToHeaders(res),
      }));
    });
    req.on("error", reject);
    req.end();
  });
}
