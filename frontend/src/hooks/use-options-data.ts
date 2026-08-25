"use client";

import useSWR from "swr";
import { fetchJson, endpoints } from "@/lib/api";
import type { ComparisonResponse, PerformanceResponse, ScalpState, ScannerResponse, StrategyState, SymbolCode, SystemStatus, TradeDeskHome, TradeRow } from "@/lib/types";

const config = { revalidateOnFocus: true, shouldRetryOnError: false, keepPreviousData: true };

export function useInstrumentData(symbol: SymbolCode) {
  const strategy = useSWR<StrategyState>(endpoints.strategy(symbol), fetchJson, { ...config, refreshInterval: 10_000 });
  const scalp = useSWR<ScalpState>(endpoints.scalp(symbol), fetchJson, { ...config, refreshInterval: 5_000 });
  const performance = useSWR<PerformanceResponse>(endpoints.performance(symbol), fetchJson, { ...config, refreshInterval: 60_000 });
  return { strategy, scalp, performance };
}

export function useComparison() {
  return useSWR<ComparisonResponse>(endpoints.comparison, fetchJson, { ...config, refreshInterval: 60_000 });
}

export function useSystemStatus() {
  return useSWR<SystemStatus>(endpoints.system, fetchJson, { ...config, refreshInterval: 15_000 });
}

export function useTradeDeskHome() {
  return useSWR<TradeDeskHome>(endpoints.tradeDeskHome, fetchJson, { ...config, refreshInterval: 10_000 });
}

export function useActiveTrades() {
  return useSWR<TradeRow[]>(endpoints.activeTrades, fetchJson, { ...config, refreshInterval: 5_000 });
}

export function useRecentTrades() {
  return useSWR<TradeRow[]>(endpoints.recentTrades, fetchJson, { ...config, refreshInterval: 15_000 });
}

export function useScannerData() {
  return useSWR<ScannerResponse>(endpoints.scanner, fetchJson, { ...config, refreshInterval: 15_000 });
}
