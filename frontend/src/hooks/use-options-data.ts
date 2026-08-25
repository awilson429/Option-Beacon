"use client";

import useSWR from "swr";
import { fetchJson, endpoints } from "@/lib/api";
import type { ActiveTrade, ComparisonResponse, JournalResponse, PerformanceResponse, ScalpState, ScannerResponse, StrategyState, SymbolCode, SystemStatus, TradeDeskHome, TradeManagementSnapshot, TradeRow } from "@/lib/types";

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
  return useSWR<ActiveTrade[]>(endpoints.activeTrades, fetchJson, { ...config, refreshInterval: 5_000 });
}

export function useRecentTrades() {
  return useSWR<TradeRow[]>(endpoints.recentTrades, fetchJson, { ...config, refreshInterval: 15_000 });
}

export function useScannerData() {
  return useSWR<ScannerResponse>(endpoints.scanner, fetchJson, { ...config, refreshInterval: 15_000 });
}

export function useJournalData(query:string) {
  return useSWR<JournalResponse>(endpoints.journal(query), fetchJson, { ...config, refreshInterval: 45_000 });
}

export function useManagementHistory(tradeId?:string, lane?:string) {
  const key = tradeId && lane ? endpoints.managementHistory(tradeId,lane) : null;
  return useSWR<TradeManagementSnapshot[]>(key, fetchJson, { ...config, revalidateOnFocus:false });
}
