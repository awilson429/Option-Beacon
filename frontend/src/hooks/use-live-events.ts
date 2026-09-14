"use client";

import {useEffect, useState} from "react";
import {API_BASE_URL, endpoints} from "@/lib/api";
import type {LiveEventEnvelope, LiveEventStatus} from "@/lib/types";

export const SSE_RECONNECT_MS = 2_000;

export function liveEventsUrl() {
  return `${API_BASE_URL}${endpoints.liveEvents}`;
}

export function parseLiveEvent(raw: string): LiveEventEnvelope | null {
  try {
    const parsed = JSON.parse(raw) as LiveEventEnvelope;
    if (!parsed || typeof parsed.event_type !== "string") return null;
    return parsed;
  } catch {
    return null;
  }
}

export function shouldRefreshSnapshot(event: LiveEventEnvelope, currentSnapshotId?: string) {
  if (event.event_type === "resync.required") return true;
  if (event.event_type !== "snapshot.changed") return false;
  if (!event.snapshot_id || !currentSnapshotId) return true;
  return event.snapshot_id !== currentSnapshotId;
}

export function useLiveEvents() {
  const [status, setStatus] = useState<LiveEventStatus>(
    () => typeof EventSource === "undefined" ? "unavailable" : "connecting",
  );
  const [lastEvent, setLastEvent] = useState<LiveEventEnvelope | null>(null);

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    let cancelled = false;
    let source: EventSource | undefined;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    const seen = new Set<string>();

    const onEnvelope = (message: MessageEvent<string>) => {
      const parsed = parseLiveEvent(message.data);
      if (!parsed) return;
      const id = parsed.event_id || message.lastEventId;
      if (id) {
        if (seen.has(id)) return;
        seen.add(id);
        if (seen.size > 100) {
          const first = seen.values().next().value;
          if (first) seen.delete(first);
        }
      }
      setLastEvent(parsed);
    };

    const connect = () => {
      if (cancelled) return;
      try {
        source = new EventSource(liveEventsUrl());
      } catch {
        queueMicrotask(() => { if (!cancelled) setStatus("unavailable"); });
        return;
      }
      source.addEventListener("snapshot.changed", onEnvelope);
      source.addEventListener("resync.required", onEnvelope);
      source.onmessage = onEnvelope;
      source.onopen = () => setStatus("open");
      source.onerror = () => {
        if (cancelled || !source) return;
        if (source.readyState === EventSource.CLOSED) {
          setStatus("closed");
          source.close();
          reconnect = setTimeout(connect, SSE_RECONNECT_MS);
        } else {
          setStatus("connecting");
        }
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnect) clearTimeout(reconnect);
      source?.close();
    };
  }, []);

  return {status, lastEvent};
}
