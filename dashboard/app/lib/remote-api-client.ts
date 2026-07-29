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

export type PreviewLatency = {
  frameId: string | null;
  previewEndToEndMs: number;
  fastApiMs: number;
  networkMs: number;
  browserDecodeMs: number;
  sourcePipelineMs: number | null;
  sourceDecodeMs: number | null;
  jpegBytes: number;
};

export type PreviewFrame = {
  objectUrl: string;
  latency: PreviewLatency;
};

function commandId(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10).join(""),
  ].join("-");
}

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
          command_id: commandId(),
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

  async preview(
    view: "before" | "after",
    signal?: AbortSignal,
  ): Promise<PreviewFrame> {
    const requestStartedWall = Date.now();
    const requestStarted = performance.now();
    const response = await fetch(
      `${this.baseUrl.replace(/\/$/, "")}/api/v3/edge/preview/${view}?v=${requestStartedWall}`,
      { cache: "no-store", signal },
    );
    const responseReceivedWall = Date.now();
    const responseReceived = performance.now();
    if (!response.ok) {
      throw new Error(`Preview API ${response.status}`);
    }
    const blob = await response.blob();
    const downloaded = performance.now();
    const objectUrl = URL.createObjectURL(blob);
    const image = new Image();
    image.src = objectUrl;
    const decodeStarted = performance.now();
    try {
      await image.decode();
    } catch (error) {
      URL.revokeObjectURL(objectUrl);
      throw error;
    }
    const decoded = performance.now();

    const numberHeader = (name: string): number | null => {
      const raw = response.headers.get(name);
      if (raw === null) return null;
      const value = Number(raw);
      return Number.isFinite(value) ? value : null;
    };
    const apiTimestamp = numberHeader("X-AIVD-API-Timestamp-Ms");
    const captureTimestamp = numberHeader("X-AIVD-Capture-Timestamp-Ms");
    const publishedTimestamp = numberHeader("X-AIVD-Published-Timestamp-Ms");
    const browserMidpointWall =
      requestStartedWall + (responseReceivedWall - requestStartedWall) / 2;
    const serverClockOffset =
      apiTimestamp === null ? 0 : apiTimestamp - browserMidpointWall;
    const frameOriginOnBrowserClock =
      (captureTimestamp ?? publishedTimestamp) === null
        ? responseReceivedWall
        : (captureTimestamp ?? publishedTimestamp)! - serverClockOffset;
    const previewEndToEndMs = Math.max(
      0,
      responseReceivedWall +
        (decoded - responseReceived) -
        frameOriginOnBrowserClock,
    );

    return {
      objectUrl,
      latency: {
        frameId: response.headers.get("X-AIVD-Frame-ID"),
        previewEndToEndMs,
        fastApiMs:
          apiTimestamp === null || publishedTimestamp === null
            ? 0
            : Math.max(0, apiTimestamp - publishedTimestamp),
        networkMs: Math.max(0, downloaded - requestStarted),
        browserDecodeMs: Math.max(0, decoded - decodeStarted),
        sourcePipelineMs: numberHeader("X-AIVD-Pipeline-Latency-Ms"),
        sourceDecodeMs: numberHeader("X-AIVD-Source-Decode-Ms"),
        jpegBytes: blob.size,
      },
    };
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
