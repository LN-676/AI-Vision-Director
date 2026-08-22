# AI Vision Director Architecture Notes

[中文](#中文) · [English](#english)

## 中文

這個目錄保存目前產品的設計邊界、資料契約與可驗證的技術決策。完整硬體、iOS 與 Desktop 三張架構圖位於 [專案 README](../../README.md#整體硬體與資料連接)。

### 文件索引

| 區域 | 文件 | 說明 |
| --- | --- | --- |
| Composition | [composition-root.md](composition-root.md) | 應用程式組裝與 dependency wiring |
| Domain | [domain-contracts.md](domain-contracts.md) | 跨 pipeline 的穩定資料契約 |
| Application | [application-layer.md](application-layer.md) | use case 與 application services |
| Vision | [vision-backends.md](vision-backends.md) | detector／tracker backend 邊界 |
| Calibration | [camera-calibration-gmc.md](camera-calibration-gmc.md) | 鏡頭校正與 Global Motion Compensation |
| Framing | [framing-engine.md](framing-engine.md) | 構圖、lead room 與 zoom 決策 |
| Identity | [identity-components.md](identity-components.md) | GID、ReID 與 identity facade |
| Identity decisions | [identity-decisions.md](identity-decisions.md) | 可稽核身份決策與 reason codes |
| Gallery | [feature-gallery-components.md](feature-gallery-components.md) | feature quality、encoder、policy 與 index |
| Gallery safety | [gallery-contamination-prevention.md](gallery-contamination-prevention.md) | feature provenance 與污染防護 |
| Persistence | [sqlite-threading.md](sqlite-threading.md) | SQLite 單一 owner worker |
| Network | [websocket-components.md](websocket-components.md) | protocol、transport、receiver、publisher 與 policy |
| Cloud | [cloud-boundaries-v3.md](cloud-boundaries-v3.md) | V3 Phase 0 query、command、event、API 與 ID mapping 邊界 |
| Cloud persistence | [postgresql-edge-sync.md](postgresql-edge-sync.md) | PostgreSQL schema、Alembic、import 與 Edge outbox |
| Public API security | [public-api-security.md](public-api-security.md) | Firebase Auth、RBAC、audit、rate limit、CORS 與 secrets |
| React dashboard | [react-dashboard.md](react-dashboard.md) | typed read-only client、operations views、UI states 與 telemetry reconnect |
| Google Cloud deployment | [google-cloud-deployment.md](google-cloud-deployment.md) | Cloud Run、Cloud SQL、Storage、Artifact Registry、Firebase、監控與成本邊界 |
| Advanced cloud | [phase6-advanced-cloud.md](phase6-advanced-cloud.md) | 多租戶、Pub/Sub、GPU benchmark、model registry、通知與 BigQuery |
| Evaluation | [offline-replay.md](offline-replay.md) | 無 UI 的可重現 replay |
| Benchmark | [benchmark-center.md](benchmark-center.md) | 最多五模型的標準格式、跑分與 live capture |
| GID benchmark | [gid-loss-benchmark.md](gid-loss-benchmark.md) | GID continuity 壓力測試與驗收標準 |
| Safety | [camera-control-policy.md](camera-control-policy.md) | dead zone、hysteresis 與安全限制 |
| Timing | [timestamp-pipeline.md](timestamp-pipeline.md) | capture-to-control 時間軸 |

## English

This directory records the current product's design boundaries, data contracts, and verifiable technical decisions. The canonical hardware, iOS, and Desktop diagrams are in the [project README](../../README.md#end-to-end-hardware-and-data-flow).

The table above is the architecture index. Together, these documents separate:

- transport from computer-vision state;
- domain contracts from UI implementation;
- identity persistence from real-time tracking;
- deterministic evaluation from live scheduling;
- framing intent from hardware safety limits.

Historical releases remain available through Git tags. These documents describe the current working tree.
- [Edge Control Plane MVP](edge-control-plane-mvp.md): local tablet Remote
  Console, SQLite command queue, heartbeat/lease safety, and future cloud
  contract.
