"use client";

import useSWR from "swr";
import { fetchJson, endpoints } from "@/lib/api";
import type { ComparisonResponse, PerformanceResponse, ScalpState, StrategyState, SymbolCode, SystemStatus } from "@/lib/types";

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
