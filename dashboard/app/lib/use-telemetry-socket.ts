"use client";

import { useEffect, useRef, useState } from "react";
import { demoEvents, type TelemetryEvent } from "./api-client";

export type SocketState =
  | "demo"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "offline";

type TelemetrySocket = {
  state: SocketState;
  attempts: number;
  events: TelemetryEvent[];
};

const MAX_EVENTS = 30;
const MAX_BACKOFF_MS = 30_000;

function parseEvent(value: unknown): TelemetryEvent | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<TelemetryEvent>;
  if (
    typeof candidate.event !== "string" ||
    typeof candidate.component !== "string" ||
    typeof candidate.timestamp_ms !== "number"
  ) {
    return null;
  }
  return {
    schema_version: candidate.schema_version ?? 1,
    session_id: candidate.session_id ?? "live",
    event: candidate.event,
    severity: candidate.severity ?? "info",
    component: candidate.component,
    reason_code: candidate.reason_code ?? null,
    timestamp_ms: candidate.timestamp_ms,
    data: candidate.data ?? {},
  };
}

export function useTelemetrySocket(url?: string): TelemetrySocket {
  const [state, setState] = useState<SocketState>(url ? "connecting" : "demo");
  const [attempts, setAttempts] = useState(0);
  const [events, setEvents] = useState<TelemetryEvent[]>(url ? [] : demoEvents);
  const attemptsRef = useRef(0);

  useEffect(() => {
    if (!url) {
      let index = 0;
      const timer = window.setInterval(() => {
        const source = demoEvents[index % demoEvents.length];
        index += 1;
        setEvents((current) => [
          { ...source, timestamp_ms: Date.now(), event: `live_${source.event}` },
          ...current,
        ].slice(0, MAX_EVENTS));
      }, 8_000);
      return () => window.clearInterval(timer);
    }

    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      if (!navigator.onLine) {
        setState("offline");
        return;
      }
      setState(attemptsRef.current === 0 ? "connecting" : "reconnecting");
      socket = new WebSocket(url);
      socket.onopen = () => {
        attemptsRef.current = 0;
        setAttempts(0);
        setState("connected");
      };
      socket.onmessage = (message) => {
        try {
          const parsed = parseEvent(JSON.parse(String(message.data)));
          if (parsed) {
            setEvents((current) => [parsed, ...current].slice(0, MAX_EVENTS));
          }
        } catch {
          // Ignore malformed telemetry frames without dropping the connection.
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        attemptsRef.current += 1;
        setAttempts(attemptsRef.current);
        setState(navigator.onLine ? "reconnecting" : "offline");
        const exponential = Math.min(
          MAX_BACKOFF_MS,
          1_000 * 2 ** Math.min(attemptsRef.current - 1, 5),
        );
        const jitter = Math.round(exponential * 0.15 * Math.random());
        reconnectTimer = window.setTimeout(connect, exponential + jitter);
      };
      socket.onerror = () => socket?.close();
    };

    const handleOnline = () => {
      if (socket?.readyState !== WebSocket.OPEN) {
        if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
        connect();
      }
    };
    const handleOffline = () => {
      setState("offline");
      socket?.close();
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    connect();

    return () => {
      stopped = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      socket?.close();
    };
  }, [url]);

  return { state, attempts, events };
}
