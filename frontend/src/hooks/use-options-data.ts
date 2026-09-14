"use client";

import {useEffect} from "react";
import useSWR from "swr";
import {useLiveEvents, shouldRefreshSnapshot} from "@/hooks/use-live-events";
import {fetchJson, endpoints} from "@/lib/api";
import type {ActiveTrade, ComparisonResponse, JournalResponse, LiveSnapshot, PerformanceResponse, ScalpState, ScannerResponse, StrategyState, SymbolCode, SystemStatus, TradeDeskHome, TradeManagementSnapshot, TradeRow} from "@/lib/types";

const config = { revalidateOnFocus: true, shouldRetryOnError: false, keepPreviousData: true };
const configuredSnapshotPoll = Number(process.env.NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_POLL_MS);
export const SNAPSHOT_POLL_INTERVAL_MS = Number.isFinite(configuredSnapshotPoll) && configuredSnapshotPoll >= 1_000
  ? configuredSnapshotPoll : 15_000;
const configuredSafetyPoll = Number(process.env.NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_SAFETY_POLL_MS);
export const SNAPSHOT_SAFETY_POLL_INTERVAL_MS = Number.isFinite(configuredSafetyPoll) && configuredSafetyPoll >= 1_000
  ? configuredSafetyPoll : 60_000;

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

export function useLiveSnapshot() {
  const events = useLiveEvents();
  const sseOpen = events.status === "open";
  const snapshot = useSWR<LiveSnapshot>(endpoints.liveSnapshot, fetchJson, {
    ...config,
    refreshInterval: sseOpen ? SNAPSHOT_SAFETY_POLL_INTERVAL_MS : SNAPSHOT_POLL_INTERVAL_MS,
    refreshWhenHidden: false,
  });

  const snapshotId = snapshot.data?.snapshot_id;
  const revalidate = snapshot.mutate;
  useEffect(() => {
    const event = events.lastEvent;
    if (!event) return;
    if (!shouldRefreshSnapshot(event, snapshotId)) return;
    void revalidate();
  }, [events.lastEvent, snapshotId, revalidate]);

  return {...snapshot, liveEventsStatus: events.status};
}

export function useJournalData(query:string) {
  return useSWR<JournalResponse>(endpoints.journal(query), fetchJson, { ...config, refreshInterval: 45_000 });
}

export function useManagementHistory(tradeId?:string, lane?:string) {
  const key = tradeId && lane ? endpoints.managementHistory(tradeId,lane) : null;
  return useSWR<TradeManagementSnapshot[]>(key, fetchJson, { ...config, revalidateOnFocus:false });
}
