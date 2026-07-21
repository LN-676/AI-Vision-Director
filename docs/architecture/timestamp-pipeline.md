# Phase 14：Timestamp Pipeline 與 Latency Compensation

Phase 14 將影格從 capture 到 control publish 的時間資料收斂成單一、版本化的 `FrameTimeline`。所有階段延遲使用本機 monotonic clock 計算；wall-clock timestamp 只用於跨裝置關聯與估計 iPhone capture-to-desktop receive transport latency。

## Clock domains

- `source_wall`：iPhone camera envelope 提供的 capture epoch milliseconds。
- `local_wall`：webcam、video、screen 等本機來源的 capture epoch milliseconds。
- `monotonic_time_ms`：desktop 內各階段 duration 與 frame age 的唯一計算基準，不受系統時間校正影響。

跨裝置 capture timestamp 不會直接混入本機 monotonic subtraction。系統只以 `received.wall_time - capture.wall_time` 估計 transport；負值或超過 5 秒會標記 `CLOCK_SKEW_REJECTED`，補償退化為 desktop receive 之後的本機 frame age。

## Timestamp stages

Timeline schema version 1 支援以下 milestones：

1. `capture_started` / `capture_completed`
2. `received`
3. `decode_started` / `decode_completed`
4. `frame_dequeued`
5. `inference_started` / `inference_completed`
6. `pipeline_started` / `pipeline_completed`
7. control message 的 `timestamp_ms`

iPhone receiver 在收到 binary envelope 時記錄 `received`，JPEG decode 前後記錄 decode marks；worker 在真正呼叫 detector backend 前後記錄 inference；pipeline 覆蓋 scene cut、GMC、identity、reframing 與 preview 的完整區段。Control policy 在實際 publish 時重新評估 timeline，因此 UI queue 或 publish wait 也會進入補償。

## Non-overlapping latency breakdown

`LatencyBreakdown` 輸出：

- `transport_ms`
- `capture_ms`
- `decode_ms`
- `inference_queue_ms`
- `inference_ms`
- `pipeline_queue_ms`
- `pipeline_ms`
- `publish_queue_ms`
- `end_to_end_ms`

`end_to_end_ms` 的遠端來源公式為：

```text
transport_ms + (evaluated_monotonic - received_monotonic)
```

本機來源則為：

```text
evaluated_monotonic - capture_started_monotonic
```

因此 transport、decode、inference 與 pipeline 不會被重複加總。相容欄位 `receive_latency_ms` 現在只代表可信的 capture-to-receive transport latency；`latency_compensation_ms` 代表有界後實際採用的補償值。

## Compensation policy

`LatencyCompensator` 將 frame age 換算為 `frames_ahead`，控制預測使用：

```text
projected_center = current_center + target_velocity * frames_ahead
```

預設同時限制最多 500 ms 與 5 個 source frames，取較小者，以免網路停頓或 stale frame 造成失控外推。輸出包含 raw/applied latency、frames ahead、clamped flag 與 reason code：

- `COMPLETE`
- `LOCAL_SOURCE`
- `CAPTURE_TIMESTAMP_MISSING`
- `CLOCK_SKEW_REJECTED`
- `COMPENSATION_CLAMPED`

所有 timestamp、breakdown 與 compensation 會進入 `FrameData`、frame telemetry、desktop diagnostics 與 outbound tracking message，供現場診斷及離線 benchmark 使用。
