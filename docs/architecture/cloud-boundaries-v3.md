# V3.0 alph1 Phase 0：上網部署邊界

版本標籤：`AI-Vision-Director V3.0 alph1`

Phase 0 只建立本機與雲端之間的穩定邊界，不把現有 CV pipeline、SQLite
或 UI 綁定到特定 HTTP framework、雲端資料庫或訊息服務。

## 邊界

- `Repository[EntityT, IdT]`：最小持久層 port；adapter 自行管理 transaction。
- `SystemStatusQuery`：提供節點狀態與分項 health checks。
- `VehicleQuery`：只讀取單一車輛或 cursor 分頁。
- `VehicleCommand`：以 caller-generated idempotency key 執行 upsert/delete。
- `EventSink`：接收 versioned、可去重放的 `EventEnvelope`。
- `VehicleIdMappingStore`：明確管理 `(node_id, local_id) <-> cloud_id`。

## ID 規則

本機 SQLite integer ID 只在建立它的 `node_id` 內有效；cloud ID 是 opaque
string，呼叫端不可解析其格式。mapping 是一對一且衝突即拒絕，不允許
last-write-wins 靜默改綁。刪除 mapping 與刪除本機車輛是兩個不同操作。

## API schema

`api/schema/openapi.v3.0-alpha1.json` 是 HTTP delivery adapter 的 OpenAPI 3.1
合約。它使用 `/api/v3`、cursor pagination 與 `Idempotency-Key`，但 domain
ports 本身不依賴 HTTP。

## Phase 1：本機 Read-only FastAPI

`autocamtracker.api` 提供以下本機唯讀 endpoints：

- `GET /api/v3/system/status`
- `GET /api/v3/vehicles` 與 `GET /api/v3/vehicles/{local_id}`
- `GET /api/v3/sessions` 與 `GET /api/v3/sessions/{session_id}`
- `GET /api/v3/events`
- `GET /openapi.json`、`GET /docs` 與 `GET /redoc`

API 使用獨立的短生命週期 SQLite connection，URI 固定為 `mode=ro` 並設定
`PRAGMA query_only=ON`。它不共用 PySide6 的 writer connection，也沒有註冊
POST、PUT、PATCH 或 DELETE route。Telemetry JSONL 讀取遇到 writer 尚未完成的
最後一行時會忽略該行，不修改來源檔案。

預設只監聽 `127.0.0.1:8080`：

```bash
ai-vision-director-api
```

## Phase 2：PostgreSQL 與 edge sync

PostgreSQL schema、Alembic migration、adapter、SQLite importer 與 durable
Edge outbox 已定義於 [postgresql-edge-sync.md](postgresql-edge-sync.md)。
本機 FastAPI 仍維持唯讀；edge mutation 經由 outbox 同步，不直接讓 Web UI
與 PySide6 共同寫入本機 Vehicle Database。
