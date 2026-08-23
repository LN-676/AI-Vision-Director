export type SystemStatus = {
  node_id: string;
  status: "ready" | "degraded";
  observed_at: string;
  version_label: string;
  deployment_mode: "local" | "cloud";
  read_only: true;
  checks: Record<string, string>;
};

export type Vehicle = {
  node_id: string;
  local_id: number;
  cloud_id: string | null;
  display_name: string;
  class_name: string;
  last_track_id: number | null;
  last_frame_index: number;
  last_seen_at: string;
  confidence: number;
  bbox: [number, number, number, number];
  center: [number, number];
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
};

export type Session = {
  session_id: string;
  started_at: string;
  last_event_at: string;
  event_count: number;
  source_file: string;
};

export type TelemetryEvent = {
  schema_version: number;
  session_id: string;
  event: string;
  severity: "debug" | "info" | "warning" | "error" | "critical" | string;
  component: string;
  reason_code: string | null;
  timestamp_ms: number;
  data: Record<string, unknown>;
};

export type Page<T> = {
  items: T[];
  next_cursor: string | null;
};

export type AccessTokenProvider = () => Promise<string | null>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface VisionApi {
  readonly mode: "live" | "demo";
  getSystemStatus(signal?: AbortSignal): Promise<SystemStatus>;
  listVehicles(signal?: AbortSignal): Promise<Page<Vehicle>>;
  listSessions(signal?: AbortSignal): Promise<Page<Session>>;
  listEvents(signal?: AbortSignal): Promise<Page<TelemetryEvent>>;
}

export class HttpVisionApi implements VisionApi {
  readonly mode = "live" as const;

  constructor(
    private readonly baseUrl: string,
    private readonly tokenProvider?: AccessTokenProvider,
  ) {}

  getSystemStatus(signal?: AbortSignal) {
    return this.request<SystemStatus>("/api/v3/system/status", signal);
  }

  listVehicles(signal?: AbortSignal) {
    return this.request<Page<Vehicle>>("/api/v3/vehicles?limit=100", signal);
  }

  listSessions(signal?: AbortSignal) {
    return this.request<Page<Session>>("/api/v3/sessions?limit=100", signal);
  }

  listEvents(signal?: AbortSignal) {
    return this.request<Page<TelemetryEvent>>("/api/v3/events?limit=100", signal);
  }

  private async request<T>(path: string, signal?: AbortSignal): Promise<T> {
    const token = await this.tokenProvider?.();
    const response = await fetch(`${this.baseUrl.replace(/\/$/, "")}${path}`, {
      signal,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!response.ok) {
      let detail: unknown;
      try {
        detail = await response.json();
      } catch {
        detail = await response.text();
      }
      throw new ApiError(`Request failed with status ${response.status}`, response.status, detail);
    }
    return (await response.json()) as T;
  }
}

const now = Date.now();
const iso = (offsetMinutes: number) =>
  new Date(now - offsetMinutes * 60_000).toISOString();

const demoVehicles: Vehicle[] = [
  {
    node_id: "edge-taipei-01",
    local_id: 12,
    cloud_id: "6b9d2d9d-8ee7-4f74-9e11-703bac24f511",
    display_name: "Hero GT",
    class_name: "sports car",
    last_track_id: 84,
    last_frame_index: 48291,
    last_seen_at: iso(0),
    confidence: 0.97,
    bbox: [413, 208, 1128, 842],
    center: [770, 525],
    created_at: iso(2880),
    updated_at: iso(0),
    metadata: { color: "cobalt", camera: "iphone-15-pro" },
  },
  {
    node_id: "edge-taipei-01",
    local_id: 19,
    cloud_id: "c9b09c18-6df6-45c4-b601-dc0bcba8b9c4",
    display_name: "Support Van",
    class_name: "van",
    last_track_id: null,
    last_frame_index: 47802,
    last_seen_at: iso(18),
    confidence: 0.88,
    bbox: [242, 196, 721, 736],
    center: [482, 466],
    created_at: iso(1440),
    updated_at: iso(18),
    metadata: { color: "graphite" },
  },
  {
    node_id: "edge-kaohsiung-02",
    local_id: 7,
    cloud_id: "c071dc11-969e-45bb-b7df-025a567f5d01",
    display_name: "Track Prototype",
    class_name: "car",
    last_track_id: 31,
    last_frame_index: 11602,
    last_seen_at: iso(3),
    confidence: 0.93,
    bbox: [611, 224, 1274, 819],
    center: [943, 522],
    created_at: iso(720),
    updated_at: iso(3),
    metadata: { color: "signal orange", rig: "dockkit-02" },
  },
];

const demoSessions: Session[] = [
  {
    session_id: "track-day-20260729-a8c2",
    started_at: iso(42),
    last_event_at: iso(0),
    event_count: 1284,
    source_file: "autocamtracker-telemetry-track-day.jsonl",
  },
  {
    session_id: "calibration-20260729-d174",
    started_at: iso(196),
    last_event_at: iso(152),
    event_count: 318,
    source_file: "autocamtracker-telemetry-calibration.jsonl",
  },
  {
    session_id: "night-run-20260728-f21b",
    started_at: iso(1035),
    last_event_at: iso(944),
    event_count: 2461,
    source_file: "autocamtracker-telemetry-night-run.jsonl",
  },
];

export const demoEvents: TelemetryEvent[] = [
  {
    schema_version: 2,
    session_id: demoSessions[0].session_id,
    event: "vehicle_lock_acquired",
    severity: "info",
    component: "identity",
    reason_code: null,
    timestamp_ms: now - 8_000,
    data: { gid: 12, confidence: 0.97, latency_ms: 42 },
  },
  {
    schema_version: 2,
    session_id: demoSessions[0].session_id,
    event: "camera_latency_warning",
    severity: "warning",
    component: "camera_stream",
    reason_code: "LATENCY_BUDGET",
    timestamp_ms: now - 38_000,
    data: { latency_ms: 126, budget_ms: 100 },
  },
  {
    schema_version: 2,
    session_id: demoSessions[0].session_id,
    event: "framing_stable",
    severity: "info",
    component: "framing",
    reason_code: null,
    timestamp_ms: now - 71_000,
    data: { mode: "close", error_x: 0.02, error_y: -0.01 },
  },
  {
    schema_version: 2,
    session_id: demoSessions[1].session_id,
    event: "gmc_recalibrated",
    severity: "debug",
    component: "vision",
    reason_code: null,
    timestamp_ms: now - 164_000,
    data: { inliers: 143, confidence: 0.91 },
  },
];

export class DemoVisionApi implements VisionApi {
  readonly mode = "demo" as const;

  private resolve<T>(value: T, signal?: AbortSignal): Promise<T> {
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => resolve(value), 360);
      signal?.addEventListener(
        "abort",
        () => {
          window.clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }

  getSystemStatus(signal?: AbortSignal) {
    return this.resolve<SystemStatus>(
      {
        node_id: "edge-taipei-01",
        status: "ready",
        observed_at: new Date(now).toISOString(),
        version_label: "AI Vision Director 3.0.0 Beta 2",
        deployment_mode: "local",
        read_only: true,
        checks: {
          identity_database: "ready",
          telemetry: "ready",
          access_mode: "read_only",
        },
      },
      signal,
    );
  }

  listVehicles(signal?: AbortSignal) {
    return this.resolve({ items: demoVehicles, next_cursor: null }, signal);
  }

  listSessions(signal?: AbortSignal) {
    return this.resolve({ items: demoSessions, next_cursor: null }, signal);
  }

  listEvents(signal?: AbortSignal) {
    return this.resolve({ items: demoEvents, next_cursor: null }, signal);
  }
}

export function createVisionApi(): VisionApi {
  const baseUrl = process.env.NEXT_PUBLIC_AIVD_API_BASE_URL?.trim();
  return baseUrl ? new HttpVisionApi(baseUrl) : new DemoVisionApi();
}
