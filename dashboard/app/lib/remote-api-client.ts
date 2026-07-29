export type CommandStatus =
  | "queued"
  | "claimed"
  | "executing"
  | "succeeded"
  | "failed"
  | "expired";

export type CommandType =
  | "start_tracking"
  | "stop_tracking"
  | "set_tracking_mode"
  | "select_target"
  | "find_target"
  | "home"
  | "emergency_stop";

export type TargetState = {
  gid: number | null;
  display_name: string | null;
  confidence: number | null;
  tracking_state: string;
  reacquiring: boolean;
};

export type EdgeCommand = {
  command_id: string;
  node_id: string;
  actor_uid: string;
  command_type: CommandType;
  parameters: Record<string, unknown>;
  priority: number;
  status: CommandStatus;
  created_at: string;
  expires_at: string;
  claimed_at: string | null;
  lease_expires_at: string | null;
  completed_at: string | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
};

export type EdgeNodeState = {
  node_id: string;
  app_version: string;
  online: boolean;
  iphone_connected: boolean;
  dockkit_ready: boolean;
  tracking_running: boolean;
  tracking_mode: string;
  current_target: TargetState | null;
  available_targets: TargetState[];
  fps: number | null;
  latency_ms: number | null;
  last_error: string | null;
  simulated: boolean;
  last_heartbeat: string;
  recent_commands: EdgeCommand[];
};

export class RemoteApi {
  constructor(private readonly baseUrl: string) {}

  async listNodes(signal?: AbortSignal): Promise<EdgeNodeState[]> {
    return this.request("/api/v3/edge/nodes", { signal });
  }

  async getNode(nodeId: string, signal?: AbortSignal): Promise<EdgeNodeState> {
    return this.request(
      `/api/v3/edge/nodes/${encodeURIComponent(nodeId)}/state`,
      { signal },
    );
  }

  async command(
    nodeId: string,
    commandType: CommandType,
    parameters: Record<string, unknown> = {},
  ): Promise<EdgeCommand> {
    return this.request(
      `/api/v3/edge/nodes/${encodeURIComponent(nodeId)}/commands`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command_id: crypto.randomUUID(),
          actor_uid: "tablet-local-operator",
          command_type: commandType,
          parameters,
          expires_at: new Date(Date.now() + 15_000).toISOString(),
        }),
      },
    );
  }

  previewUrl(view: "before" | "after", revision: string): string {
    const base = this.baseUrl.replace(/\/$/, "");
    return `${base}/api/v3/edge/preview/${view}?v=${encodeURIComponent(revision)}`;
  }

  private async request<T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> {
    const response = await fetch(`${this.baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      cache: "no-store",
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Control API ${response.status}: ${detail}`);
    }
    return (await response.json()) as T;
  }
}

export function createRemoteApi(): RemoteApi {
  const baseUrl =
    process.env.NEXT_PUBLIC_AIVD_API_BASE_URL?.trim() ||
    "http://127.0.0.1:8080";
  return new RemoteApi(baseUrl);
}
