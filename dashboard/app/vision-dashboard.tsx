"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createVisionApi,
  type Page,
  type Session,
  type SystemStatus,
  type TelemetryEvent,
  type Vehicle,
} from "./lib/api-client";
import {
  useTelemetrySocket,
  type SocketState,
} from "./lib/use-telemetry-socket";

type View = "overview" | "vehicles" | "sessions" | "events";
type Loadable<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "error"; message: string };

const nav: Array<{ id: View; label: string; glyph: string }> = [
  { id: "overview", label: "Overview", glyph: "OV" },
  { id: "vehicles", label: "Vehicles", glyph: "VH" },
  { id: "sessions", label: "Sessions", glyph: "SS" },
  { id: "events", label: "Events", glyph: "EV" },
];

const initialPage = <T,>(): Loadable<Page<T>> => ({ state: "loading" });

function timeAgo(value: string | number): string {
  const timestamp = typeof value === "number" ? value : Date.parse(value);
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function duration(start: string, end: string): string {
  const minutes = Math.max(
    1,
    Math.round((Date.parse(end) - Date.parse(start)) / 60_000),
  );
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function label(value: string): string {
  return value.replaceAll("_", " ");
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected request failure";
}

function LoadingBlock({ rows = 4 }: { rows?: number }) {
  return (
    <div className="loading-stack" aria-label="Loading data" role="status">
      {Array.from({ length: rows }, (_, index) => (
        <span className="skeleton-line" key={index} />
      ))}
    </div>
  );
}

function StatePanel({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: () => void;
}) {
  return (
    <div className="state-panel">
      <span className="state-mark">!</span>
      <h3>{title}</h3>
      <p>{detail}</p>
      {action ? (
        <button className="button-secondary" onClick={action} type="button">
          Retry request
        </button>
      ) : null}
    </div>
  );
}

function SocketBadge({
  state,
  attempts,
}: {
  state: SocketState;
  attempts: number;
}) {
  const copy: Record<SocketState, string> = {
    demo: "Simulated live",
    connecting: "Connecting",
    connected: "Live telemetry",
    reconnecting: `Reconnecting · ${attempts}`,
    offline: "Network offline",
  };
  return (
    <span className={`socket-badge socket-${state}`}>
      <i aria-hidden="true" />
      {copy[state]}
    </span>
  );
}

function VehicleTable({
  vehicles,
  compact = false,
}: {
  vehicles: Vehicle[];
  compact?: boolean;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Vehicle</th>
            <th>Class</th>
            <th>Confidence</th>
            <th>Track</th>
            {!compact ? <th>Edge node</th> : null}
            <th>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {vehicles.map((vehicle) => (
            <tr key={`${vehicle.node_id}-${vehicle.local_id}`}>
              <td>
                <strong>{vehicle.display_name}</strong>
                <small>#{vehicle.local_id.toString().padStart(3, "0")}</small>
              </td>
              <td>{vehicle.class_name}</td>
              <td>
                <span className="confidence">
                  <i style={{ width: `${vehicle.confidence * 100}%` }} />
                </span>
                {(vehicle.confidence * 100).toFixed(0)}%
              </td>
              <td>
                <span
                  className={`status-pill ${
                    vehicle.last_track_id === null ? "idle" : "active"
                  }`}
                >
                  {vehicle.last_track_id === null
                    ? "Idle"
                    : `Track ${vehicle.last_track_id}`}
                </span>
              </td>
              {!compact ? (
                <td className="mono">{vehicle.node_id}</td>
              ) : null}
              <td>{timeAgo(vehicle.last_seen_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventFeed({
  events,
  limit,
}: {
  events: TelemetryEvent[];
  limit?: number;
}) {
  return (
    <div className="event-feed">
      {events.slice(0, limit).map((event, index) => (
        <article
          className={`event-row severity-${event.severity}`}
          key={`${event.timestamp_ms}-${event.event}-${index}`}
        >
          <span className="event-node" aria-hidden="true" />
          <div>
            <strong>{label(event.event)}</strong>
            <p>
              {event.component}
              {event.reason_code ? ` · ${event.reason_code}` : ""}
            </p>
          </div>
          <time dateTime={new Date(event.timestamp_ms).toISOString()}>
            {timeAgo(event.timestamp_ms)}
          </time>
        </article>
      ))}
    </div>
  );
}

export function VisionDashboard() {
  const api = useMemo(() => createVisionApi(), []);
  const [view, setView] = useState<View>("overview");
  const [status, setStatus] = useState<Loadable<SystemStatus>>({
    state: "loading",
  });
  const [vehicles, setVehicles] =
    useState<Loadable<Page<Vehicle>>>(initialPage);
  const [sessions, setSessions] =
    useState<Loadable<Page<Session>>>(initialPage);
  const [events, setEvents] =
    useState<Loadable<Page<TelemetryEvent>>>(initialPage);
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("all");
  const [refreshKey, setRefreshKey] = useState(0);
  const [clock, setClock] = useState(() => new Date());
  const socket = useTelemetrySocket(
    process.env.NEXT_PUBLIC_AIVD_WS_URL?.trim() || undefined,
  );

  const refresh = useCallback(() => {
    setStatus({ state: "loading" });
    setVehicles({ state: "loading" });
    setSessions({ state: "loading" });
    setEvents({ state: "loading" });
    setRefreshKey((value) => value + 1);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    api
      .getSystemStatus(controller.signal)
      .then((data) => setStatus({ state: "ready", data }))
      .catch((error) => {
        if (!controller.signal.aborted) {
          setStatus({ state: "error", message: messageOf(error) });
        }
      });
    api
      .listVehicles(controller.signal)
      .then((data) => setVehicles({ state: "ready", data }))
      .catch((error) => {
        if (!controller.signal.aborted) {
          setVehicles({ state: "error", message: messageOf(error) });
        }
      });
    api
      .listSessions(controller.signal)
      .then((data) => setSessions({ state: "ready", data }))
      .catch((error) => {
        if (!controller.signal.aborted) {
          setSessions({ state: "error", message: messageOf(error) });
        }
      });
    api
      .listEvents(controller.signal)
      .then((data) => setEvents({ state: "ready", data }))
      .catch((error) => {
        if (!controller.signal.aborted) {
          setEvents({ state: "error", message: messageOf(error) });
        }
      });

    return () => controller.abort();
  }, [api, refreshKey]);

  const mergedEvents = useMemo(() => {
    const initial = events.state === "ready" ? events.data.items : [];
    const seen = new Set<string>();
    return [...socket.events, ...initial].filter((event) => {
      const key = `${event.timestamp_ms}:${event.session_id}:${event.event}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [events, socket.events]);

  const title = nav.find((item) => item.id === view)?.label ?? "Overview";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <i />
          </span>
          <div>
            <strong>AI Vision Director</strong>
            <small>Mission Control</small>
          </div>
        </div>
        <nav aria-label="Dashboard">
          {nav.map((item) => (
            <button
              aria-current={view === item.id ? "page" : undefined}
              className={view === item.id ? "active" : ""}
              key={item.id}
              onClick={() => setView(item.id)}
              type="button"
            >
              <span>{item.glyph}</span>
              {item.label}
            </button>
          ))}
          <a href="/remote">
            <span>RC</span>
            Remote
          </a>
        </nav>
        <div className="sidebar-status">
          <p>EDGE NETWORK</p>
          <strong>
            <i className="signal-dot" />
            {status.state === "ready" ? status.data.node_id : "Awaiting node"}
          </strong>
          <SocketBadge state={socket.state} attempts={socket.attempts} />
          <small>
            {api.mode === "demo"
              ? "Demo data · configure API URL for live mode"
              : "Read-only API · protected writes"}
          </small>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <span className="eyebrow">OPERATIONS / {title.toUpperCase()}</span>
            <h1>{title}</h1>
          </div>
          <div className="topbar-actions">
            <div className="clock">
              <strong>
                {clock.toLocaleTimeString("en-GB", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </strong>
              <small>
                {clock.toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}
              </small>
            </div>
            <button className="icon-button" onClick={refresh} type="button">
              Refresh
            </button>
          </div>
        </header>

        <div className="content">
          {view === "overview" ? (
            <Overview
              events={mergedEvents}
              onNavigate={setView}
              sessions={sessions}
              status={status}
              vehicles={vehicles}
            />
          ) : null}
          {view === "vehicles" ? (
            <VehiclesView
              resource={vehicles}
              retry={refresh}
              search={search}
              setSearch={setSearch}
            />
          ) : null}
          {view === "sessions" ? (
            <SessionsView resource={sessions} retry={refresh} />
          ) : null}
          {view === "events" ? (
            <EventsView
              events={mergedEvents}
              initial={events}
              retry={refresh}
              severity={severity}
              setSeverity={setSeverity}
            />
          ) : null}
        </div>
        <footer>
          <span>
            AI-Vision-Director V3.0.0b1 ·{" "}
            {api.mode === "demo" ? "Preview mode" : "Live mode"}
          </span>
          <span>Read-only dashboard</span>
        </footer>
      </main>
    </div>
  );
}

function Overview({
  events,
  onNavigate,
  sessions,
  status,
  vehicles,
}: {
  events: TelemetryEvent[];
  onNavigate: (view: View) => void;
  sessions: Loadable<Page<Session>>;
  status: Loadable<SystemStatus>;
  vehicles: Loadable<Page<Vehicle>>;
}) {
  const vehicleItems = vehicles.state === "ready" ? vehicles.data.items : [];
  const sessionItems = sessions.state === "ready" ? sessions.data.items : [];
  const cards = [
    {
      label: "Tracked vehicles",
      value: vehicles.state === "ready" ? vehicleItems.length : "—",
      meta: `${vehicleItems.filter((item) => item.last_track_id !== null).length} active tracks`,
      tone: "cyan",
    },
    {
      label: "Capture sessions",
      value: sessions.state === "ready" ? sessionItems.length : "—",
      meta: `${sessionItems.reduce((sum, item) => sum + item.event_count, 0).toLocaleString()} events`,
      tone: "blue",
    },
    {
      label: "System health",
      value: status.state === "ready" ? status.data.status.toUpperCase() : "—",
      meta:
        status.state === "ready"
          ? `${Object.values(status.data.checks).filter((check) => check === "ready").length} checks ready`
          : "Awaiting status",
      tone: "green",
    },
    {
      label: "Warnings",
      value: events.filter((event) => event.severity === "warning").length,
      meta: "Across current feed",
      tone: "amber",
    },
  ];

  return (
    <>
      <section className="metric-grid" aria-label="Operational summary">
        {cards.map((card) => (
          <article className={`metric-card tone-${card.tone}`} key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
            <small>{card.meta}</small>
          </article>
        ))}
      </section>

      <section className="overview-grid">
        <article className="panel pulse-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">LAST 60 MINUTES</span>
              <h2>Operations pulse</h2>
            </div>
            <span className="status-pill active">Nominal</span>
          </div>
          <div className="pulse-chart" aria-label="Telemetry activity chart">
            {[36, 49, 42, 67, 61, 81, 72, 88, 65, 76, 92, 84].map(
              (height, index) => (
                <i
                  key={index}
                  style={{ height: `${height}%` }}
                  title={`${height} events`}
                />
              ),
            )}
          </div>
          <div className="chart-axis">
            <span>60m</span>
            <span>45m</span>
            <span>30m</span>
            <span>15m</span>
            <span>Now</span>
          </div>
        </article>
        <article className="panel event-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">STREAM</span>
              <h2>Latest telemetry</h2>
            </div>
            <button className="text-button" onClick={() => onNavigate("events")}>
              View all
            </button>
          </div>
          {events.length ? (
            <EventFeed events={events} limit={4} />
          ) : (
            <StatePanel
              detail="Events will appear when a node begins streaming."
              title="No telemetry yet"
            />
          )}
        </article>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">IDENTITY REGISTRY</span>
            <h2>Vehicle activity</h2>
          </div>
          <button className="text-button" onClick={() => onNavigate("vehicles")}>
            Open registry
          </button>
        </div>
        {vehicles.state === "loading" ? <LoadingBlock rows={3} /> : null}
        {vehicles.state === "error" ? (
          <StatePanel
            detail={vehicles.message}
            title="Vehicle data unavailable"
          />
        ) : null}
        {vehicles.state === "ready" && vehicleItems.length ? (
          <VehicleTable compact vehicles={vehicleItems.slice(0, 4)} />
        ) : null}
        {vehicles.state === "ready" && !vehicleItems.length ? (
          <StatePanel
            detail="Detected vehicles will appear in the identity registry."
            title="No vehicles recorded"
          />
        ) : null}
      </section>
    </>
  );
}

function VehiclesView({
  resource,
  retry,
  search,
  setSearch,
}: {
  resource: Loadable<Page<Vehicle>>;
  retry: () => void;
  search: string;
  setSearch: (value: string) => void;
}) {
  const items =
    resource.state === "ready"
      ? resource.data.items.filter((vehicle) =>
          `${vehicle.display_name} ${vehicle.class_name} ${vehicle.node_id}`
            .toLowerCase()
            .includes(search.toLowerCase()),
        )
      : [];
  return (
    <section className="panel page-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">CLOUD / LOCAL IDENTITY MAP</span>
          <h2>Vehicle registry</h2>
        </div>
        <label className="search-box">
          <span>Search</span>
          <input
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Vehicle, class, or node"
            type="search"
            value={search}
          />
        </label>
      </div>
      {resource.state === "loading" ? <LoadingBlock rows={6} /> : null}
      {resource.state === "error" ? (
        <StatePanel
          action={retry}
          detail={resource.message}
          title="Could not load vehicles"
        />
      ) : null}
      {resource.state === "ready" && items.length ? (
        <VehicleTable vehicles={items} />
      ) : null}
      {resource.state === "ready" && !items.length ? (
        <StatePanel
          detail={
            search
              ? `No vehicle matches “${search}”.`
              : "Detected vehicles will appear after the first identity event."
          }
          title={search ? "No matching vehicles" : "Registry is empty"}
        />
      ) : null}
    </section>
  );
}

function SessionsView({
  resource,
  retry,
}: {
  resource: Loadable<Page<Session>>;
  retry: () => void;
}) {
  if (resource.state === "loading") return <LoadingBlock rows={6} />;
  if (resource.state === "error") {
    return (
      <StatePanel
        action={retry}
        detail={resource.message}
        title="Could not load sessions"
      />
    );
  }
  if (!resource.data.items.length) {
    return (
      <StatePanel
        detail="Capture sessions will appear after the first telemetry import."
        title="No sessions recorded"
      />
    );
  }
  return (
    <section className="session-grid">
      {resource.data.items.map((session, index) => (
        <article className="session-card" key={session.session_id}>
          <div className="session-top">
            <span className="session-index">
              {(index + 1).toString().padStart(2, "0")}
            </span>
            <span
              className={`status-pill ${index === 0 ? "active" : "idle"}`}
            >
              {index === 0 ? "Recent" : "Archived"}
            </span>
          </div>
          <h2>{session.session_id}</h2>
          <p className="mono">{session.source_file}</p>
          <dl>
            <div>
              <dt>Duration</dt>
              <dd>{duration(session.started_at, session.last_event_at)}</dd>
            </div>
            <div>
              <dt>Events</dt>
              <dd>{session.event_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Last signal</dt>
              <dd>{timeAgo(session.last_event_at)}</dd>
            </div>
          </dl>
        </article>
      ))}
    </section>
  );
}

function EventsView({
  events,
  initial,
  retry,
  severity,
  setSeverity,
}: {
  events: TelemetryEvent[];
  initial: Loadable<Page<TelemetryEvent>>;
  retry: () => void;
  severity: string;
  setSeverity: (value: string) => void;
}) {
  const severities = ["all", "info", "warning", "error", "debug"];
  const filtered =
    severity === "all"
      ? events
      : events.filter((event) => event.severity === severity);
  return (
    <section className="panel page-panel">
      <div className="panel-heading event-heading">
        <div>
          <span className="eyebrow">APPEND-ONLY EVENT SINK</span>
          <h2>Telemetry events</h2>
        </div>
        <div className="filter-row" aria-label="Filter event severity">
          {severities.map((item) => (
            <button
              aria-pressed={severity === item}
              className={severity === item ? "selected" : ""}
              key={item}
              onClick={() => setSeverity(item)}
              type="button"
            >
              {item}
            </button>
          ))}
        </div>
      </div>
      {initial.state === "loading" && !events.length ? (
        <LoadingBlock rows={7} />
      ) : null}
      {initial.state === "error" && !events.length ? (
        <StatePanel
          action={retry}
          detail={initial.message}
          title="Could not load events"
        />
      ) : null}
      {filtered.length ? <EventFeed events={filtered} /> : null}
      {!filtered.length && initial.state !== "loading" ? (
        <StatePanel
          detail={
            severity === "all"
              ? "The stream is connected; waiting for the next node event."
              : `No ${severity} events are present in this feed.`
          }
          title="No events to display"
        />
      ) : null}
    </section>
  );
}
