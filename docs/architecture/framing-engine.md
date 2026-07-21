# Phase 15：FramingEngine

Phase 15 將構圖決策從 OpenCV render 中抽離。`FramingEngine` 是 renderer-independent subsystem，輸出完整 `FramingDecision`；`Reframer` 只依 crop window 產生畫面，WebSocket control policy 則使用同一份 anchor、error 與 zoom target 控制實體相機。

## Framing profile

每個 framing mode 定義 framing anchor 與 desired subject scale：

| Mode | Desired subject width / output width |
| --- | ---: |
| `wide` | 0.30 |
| `medium` | 0.48 |
| `close` | 0.68 |

Anchor 使用 normalized output coordinates；`(0.5, 0.5)` 代表置中。自訂 profile 可為不同 shot mode 設定不同靜態 anchor，而不需要修改 render 或 motor control。

## Velocity-based lead room

Identity subsystem 提供的 target velocity 會先依 source frame 寬高正規化，再套用可設定 gain：

```text
lead_x = clamp((velocity_x / frame_width) * horizontal_gain, ±max_horizontal_lead)
lead_y = clamp((velocity_y / frame_height) * vertical_gain, ±max_vertical_lead)
anchor = base_anchor - lead
```

車輛向右移動時 anchor 會向左，讓畫面右側保留 lead room；向上或向下亦同。低於 velocity deadband 時保持靜態 anchor，避免偵測抖動造成構圖漂移。預設水平 lead 最多 0.18、垂直最多 0.10。

## Desired subject scale 與 zoom target

Engine 先找出符合 output aspect ratio 的最大 source crop，再以 union subject bbox 計算 zoom：

```text
width_zoom = desired_subject_scale * base_crop_width / subject_width
height_safe_zoom = max_subject_height_scale * base_crop_height / subject_height
raw_zoom_target = clamp(min(width_zoom, height_safe_zoom), min_zoom, max_zoom)
```

`height_safe_zoom` 避免高車身或多目標 union bbox 被上下裁切。預設 zoom 範圍為 1x–8x，並以 zoom smoothing 產生實際 `zoom_target`。數位 crop 與 outbound physical-camera command 都使用此動態 target，不再只依 wide/medium/close 傳送固定倍率。

## Crop placement 與 boundary handling

Crop 原點由 subject anchor 反推：

```text
crop_center = subject_center + (0.5 - anchor) * crop_size
```

Crop center 使用 dead zone 與 exponential smoothing。若 crop 超出來源畫面，engine 會 clamp 到合法範圍，輸出 `boundary_clamped=true` 以及 clamp 後的 `realized_anchor`。這讓下游可區分「構圖意圖」與「受畫面邊界限制的實際位置」。

## Output contract

每個 `FramingDecision`／`FramingStatus` 包含：

- `framing_anchor`、`realized_anchor`、`lead_room`
- `desired_subject_scale`、`actual_subject_scale`
- `zoom_target`、`raw_zoom_target`
- `crop_window`、subject bbox/center、velocity
- `boundary_clamped` 與 reason code

Reason codes 為 `NO_SUBJECT`、`STATIC_ANCHOR`、`VELOCITY_LEAD`、`BOUNDARY_CLAMPED`。完整構圖資料會進入 frame telemetry、desktop diagnostics 與 tracking control message。

## Ownership boundary

Bootstrap 建立單一 `FramingEngine` 並注入 `Reframer` 與 application container。Pipeline 在 identity 更新後取得 velocity，再呼叫 Reframer/engine。FramingEngine 不依賴 OpenCV、UI、WebSocket 或 motor state，因此可用離線 replay 輸入 bbox 與 velocity 做 deterministic benchmark。
