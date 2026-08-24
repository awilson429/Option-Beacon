import type { ComparisonResponse, PerformanceResponse, ScalpState, StrategyState, SymbolCode, SystemStatus, TradeDeskHome, TradeRow } from "./types";

const configuredBase = process.env.NEXT_PUBLIC_OPTIONBEACON_API_URL?.replace(/\/$/, "");
export const API_BASE_URL = configuredBase || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new ApiError(response.status, `OptionBeacon API returned ${response.status}`);
  return response.json() as Promise<T>;
}

export const endpoints = {
  strategy: (symbol: SymbolCode) => `/api/options-desk/${symbol}`,
  scalp: (symbol: SymbolCode) => `/api/scalp/${symbol}`,
  performance: (symbol: SymbolCode) => `/api/scalp/${symbol}/performance`,
  comparison: "/api/scalp/compare",
  system: "/api/system/status",
  tradeDeskHome: "/api/trade-desk",
  activeTrades: "/api/trades/active",
  recentTrades: "/api/trades/recent?limit=12",
} as const;

export const api = {
  strategy: (symbol: SymbolCode) => fetchJson<StrategyState>(endpoints.strategy(symbol)),
  scalp: (symbol: SymbolCode) => fetchJson<ScalpState>(endpoints.scalp(symbol)),
  performance: (symbol: SymbolCode) => fetchJson<PerformanceResponse>(endpoints.performance(symbol)),
  comparison: () => fetchJson<ComparisonResponse>(endpoints.comparison),
  system: () => fetchJson<SystemStatus>(endpoints.system),
  tradeDeskHome: () => fetchJson<TradeDeskHome>(endpoints.tradeDeskHome),
  activeTrades: () => fetchJson<TradeRow[]>(endpoints.activeTrades),
  recentTrades: () => fetchJson<TradeRow[]>(endpoints.recentTrades),
};
