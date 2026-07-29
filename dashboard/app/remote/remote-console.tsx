"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  createRemoteApi,
  type CommandType,
  type EdgeCommand,
  type EdgeNodeState,
} from "../lib/remote-api-client";

type LoadState =
  | { kind: "loading" }
  | { kind: "offline"; message: string }
  | { kind: "empty" }
  | { kind: "ready"; node: EdgeNodeState };

const pretty = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

function StatusItem({
  label,
  ready,
  value,
}: {
  label: string;
  ready: boolean;
  value: string;
}) {
  return (
    <div className="remote-status-item">
      <span className={ready ? "remote-dot ready" : "remote-dot unavailable"} />
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

export function RemoteConsole() {
  const api = useMemo(() => createRemoteApi(), []);
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [sending, setSending] = useState<CommandType | null>(null);
  const [feedback, setFeedback] = useState<EdgeCommand | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [emergencyArmed, setEmergencyArmed] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        if (nodeId) {
          const node = await api.getNode(nodeId, signal);
          setState({ kind: "ready", node });
          const newest = node.recent_commands[0];
          if (newest) setFeedback(newest);
          return;
        }
        const nodes = await api.listNodes(signal);
        if (nodes.length === 0) {
          setState({ kind: "empty" });
          return;
        }
        setNodeId(nodes[0].node_id);
        setState({ kind: "ready", node: nodes[0] });
      } catch (caught) {
        if (!signal?.aborted) {
          setState({
            kind: "offline",
            message:
              caught instanceof Error ? caught.message : "Control API unavailable",
          });
        }
      }
    },
    [api, nodeId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const initial = window.setTimeout(() => void load(controller.signal), 0);
    const timer = window.setInterval(() => void load(controller.signal), 1000);
    return () => {
      controller.abort();
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [load]);

  useEffect(() => {
    if (!emergencyArmed) return;
    const timer = window.setTimeout(() => setEmergencyArmed(false), 5000);
    return () => window.clearTimeout(timer);
  }, [emergencyArmed]);

  const send = useCallback(
    async (
      commandType: CommandType,
      parameters: Record<string, unknown> = {},
    ) => {
      if (!nodeId || sending) return;
      setSending(commandType);
      setError(null);
      try {
        const command = await api.command(nodeId, commandType, parameters);
        setFeedback(command);
        await load();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Command failed");
      } finally {
        setSending(null);
      }
    },
    [api, load, nodeId, sending],
  );

  const node = state.kind === "ready" ? state.node : null;
  const online = Boolean(node?.online);
  const target = node?.current_target;

  return (
    <main className="remote-shell">
      <header className="remote-header">
        <Link className="remote-back" href="/">
          ← Mission Control
        </Link>
        <div>
          <span className="eyebrow">EDGE OPERATIONS / TABLET</span>
          <h1>AI Vision Director Remote Console</h1>
        </div>
        <span className={`remote-live ${online ? "online" : "offline"}`}>
          {node?.simulated ? "DEMO / SIMULATED" : online ? "LIVE" : "OFFLINE"}
        </span>
      </header>

      {state.kind === "loading" ? (
        <section className="remote-state" role="status">
          Connecting to Edge control plane…
        </section>
      ) : null}
      {state.kind === "offline" ? (
        <section className="remote-state error" role="alert">
          <strong>Control API Offline</strong>
          <p>{state.message}</p>
          <p>Desktop live tracking remains local and is not stopped.</p>
        </section>
      ) : null}
      {state.kind === "empty" ? (
        <section className="remote-state">
          <strong>No Edge Mac heartbeat yet</strong>
          <p>Start the Desktop Edge Agent, then keep this page open.</p>
        </section>
      ) : null}

      {node ? (
        <div className="remote-content">
          <section className="remote-status-strip" aria-label="System status">
            <StatusItem
              label="Edge Mac"
              ready={node.online}
              value={node.online ? "Online" : "Offline"}
            />
            <StatusItem
              label="iPhone Camera"
              ready={node.iphone_connected}
              value={node.iphone_connected ? "Connected" : "Disconnected"}
            />
            <StatusItem
              label="DockKit"
              ready={node.dockkit_ready}
              value={node.dockkit_ready ? "Ready" : "Unavailable"}
            />
            <StatusItem
              label="AI Tracking"
              ready={node.tracking_running}
              value={node.tracking_running ? "Running" : "Stopped"}
            />
            <div className="remote-metric">
              <small>FPS / LATENCY</small>
              <strong>
                {node.fps?.toFixed(1) ?? "—"} /{" "}
                {node.latency_ms?.toFixed(0) ?? "—"} ms
              </strong>
            </div>
            <div className="remote-metric">
              <small>LAST HEARTBEAT</small>
              <strong>{new Date(node.last_heartbeat).toLocaleTimeString()}</strong>
            </div>
          </section>

          {node.last_error ? (
            <div className="remote-alert" role="alert">
              {node.last_error}
            </div>
          ) : null}

          <section className="remote-monitor-section" aria-label="Live monitors">
            <div className="remote-monitor-heading">
              <div>
                <span className="eyebrow">LIVE VISION</span>
                <h2>Before / After Monitors</h2>
              </div>
              <span>{online ? "1 FPS tablet preview" : "Waiting for Edge Mac"}</span>
            </div>
            <div className="remote-monitor-grid">
              <figure className="remote-monitor">
                <figcaption>
                  <strong>BEFORE</strong>
                  <span>Detection + identity overlay</span>
                </figcaption>
                <div className="remote-monitor-screen">
                  <img
                    alt="Before detection monitor"
                    src={api.previewUrl("before", node.last_heartbeat)}
                  />
                  <span className="remote-monitor-corner">INPUT</span>
                </div>
              </figure>
              <figure className="remote-monitor">
                <figcaption>
                  <strong>AFTER</strong>
                  <span>AI reframed output</span>
                </figcaption>
                <div className="remote-monitor-screen">
                  <img
                    alt="After reframed monitor"
                    src={api.previewUrl("after", node.last_heartbeat)}
                  />
                  <span className="remote-monitor-corner">PROGRAM</span>
                </div>
              </figure>
            </div>
          </section>

          <div className="remote-grid">
            <section className="remote-card remote-target">
              <div className="remote-card-heading">
                <span className="eyebrow">CURRENT TARGET</span>
                <span className={`status-pill ${target ? "active" : "idle"}`}>
                  {target?.reacquiring ? "Reacquiring" : target ? "Locked" : "Empty"}
                </span>
              </div>
              {target ? (
                <>
                  <strong className="remote-gid">GID {target.gid ?? "—"}</strong>
                  <h2>{target.display_name ?? "Unnamed target"}</h2>
                  <dl className="remote-detail-list">
                    <div>
                      <dt>Confidence</dt>
                      <dd>
                        {target.confidence === null
                          ? "—"
                          : `${(target.confidence * 100).toFixed(0)}%`}
                      </dd>
                    </div>
                    <div>
                      <dt>State</dt>
                      <dd>{pretty(target.tracking_state)}</dd>
                    </div>
                  </dl>
                </>
              ) : (
                <div className="remote-empty">
                  No target selected. Available GIDs will appear after Desktop
                  identity detection.
                </div>
              )}
              <div className="target-list">
                {node.available_targets.map((item) => (
                  <button
                    disabled={!online || sending !== null || item.gid === null}
                    key={item.gid}
                    onClick={() =>
                      void send("select_target", { target_gid: item.gid })
                    }
                    type="button"
                  >
                    GID {item.gid} · {item.display_name ?? "Unnamed"}
                  </button>
                ))}
              </div>
            </section>

            <section className="remote-card">
              <span className="eyebrow">TRACKING MODE</span>
              <div className="remote-mode-grid">
                {[
                  ["ai_tracking", "AI Tracking"],
                  ["fixed_cut", "Fixed Cut"],
                  ["in_out_auto", "In/Out Auto"],
                ].map(([mode, modeLabel]) => (
                  <button
                    className={node.tracking_mode === mode ? "selected" : ""}
                    disabled={!online || sending !== null}
                    key={mode}
                    onClick={() =>
                      void send("set_tracking_mode", { mode })
                    }
                    type="button"
                  >
                    {modeLabel}
                  </button>
                ))}
              </div>

              <span className="eyebrow remote-controls-label">CONTROL</span>
              <div className="remote-control-grid">
                <button
                  className="remote-action primary"
                  disabled={!online || sending !== null}
                  onClick={() => void send("start_tracking")}
                  type="button"
                >
                  Start Tracking
                </button>
                <button
                  className="remote-action"
                  disabled={!online || sending !== null}
                  onClick={() => void send("stop_tracking")}
                  type="button"
                >
                  Stop Tracking
                </button>
                <button
                  className="remote-action"
                  disabled={!online || sending !== null}
                  onClick={() => void send("home")}
                  type="button"
                >
                  Home
                </button>
                <button
                  className="remote-action"
                  disabled={!online || sending !== null || target?.gid == null}
                  onClick={() =>
                    void send("find_target", { target_gid: target?.gid })
                  }
                  type="button"
                >
                  Find Target
                </button>
              </div>
              <button
                aria-label={
                  emergencyArmed
                    ? "Confirm Emergency Stop"
                    : "Arm Emergency Stop"
                }
                className={`emergency-button ${emergencyArmed ? "armed" : ""}`}
                disabled={!online || sending !== null}
                onClick={() => {
                  if (!emergencyArmed) {
                    setEmergencyArmed(true);
                    return;
                  }
                  setEmergencyArmed(false);
                  void send("emergency_stop");
                }}
                type="button"
              >
                {emergencyArmed
                  ? "TAP AGAIN — CONFIRM EMERGENCY STOP"
                  : "EMERGENCY STOP · TAP TWICE"}
              </button>
            </section>
          </div>

          <section className="remote-card remote-feedback">
            <div className="remote-card-heading">
              <span className="eyebrow">COMMAND FEEDBACK</span>
              {sending ? <span>Sending {pretty(sending)}…</span> : null}
            </div>
            {error ? <div className="remote-alert">{error}</div> : null}
            {feedback ? (
              <div className={`command-banner command-${feedback.status}`}>
                <strong>{pretty(feedback.command_type)}</strong>
                <span>{pretty(feedback.status)}</span>
                <small>{feedback.error_message ?? feedback.command_id}</small>
              </div>
            ) : (
              <div className="remote-empty">No commands sent in this session.</div>
            )}
            <div className="remote-events">
              {node.recent_commands.slice(0, 8).map((command) => (
                <article key={command.command_id}>
                  <span className={`remote-dot command-${command.status}`} />
                  <strong>{pretty(command.command_type)}</strong>
                  <span>{pretty(command.status)}</span>
                  <time>{new Date(command.created_at).toLocaleTimeString()}</time>
                </article>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
