# Phase 16：CameraControlPolicy

Phase 16 在 FramingEngine 的構圖意圖與 outbound tracking command 之間加入單一、stateful `CameraControlPolicy`。它不讀取 OpenCV frame，也不操作 DockKit；輸入是 normalized framing error、zoom target 與 identity uncertainty，輸出是受限且可稽核的 camera command。iOS 端仍保留硬體速度限制，形成 desktop policy 加 device safety 的雙層保護。

## Control sequence

Tracking request 依序經過：

1. dead zone 與 hysteresis gate；
2. proportional velocity request；
3. low-pass smoothing；
4. max velocity clamp；
5. max acceleration slew limit；
6. zoom ramp；
7. uncertainty safety gate。

`error_x` 是畫面右方為正，對應正 yaw command；`error_y` 是畫面下方為正，policy 內部轉為負 pitch command。輸出的 `error_x/error_y` 保持既有 wire semantics，因此舊版 iOS parser 仍可使用；`camera_control` audit payload 另提供實際 yaw/pitch velocity 與 acceleration。

## Dead zone 與 hysteresis

Axis 未啟動時，error 必須到達 `dead_zone_enter` 才開始控制；啟動後要降到 `dead_zone_exit` 以下才離開。預設值為：

```text
enter = 0.060
exit  = 0.035
```

介於兩者時輸出 `HYSTERESIS_TRACKING`，避免 target 在臨界值附近反覆啟停。Dead-zone target 為零；一般減速仍服從 acceleration limit。Identity uncertainty 與 target lost 是 safety stop，可立即歸零而不等待 slew-down。

## Smoothing、velocity 與 acceleration

每軸先計算 proportional request，再以 low-pass alpha 平滑：

```text
filtered = previous + alpha * (requested - previous)
```

預設 yaw/pitch 最大速度分別為 0.35／0.22，最大加速度為 1.20／0.80 per second。Policy 使用 ControlPublisher 的 monotonic publish time 計算 delta time；過大的排程間隔會被 clamp，避免 stall 後第一筆 command 跳變。

## Zoom ramp 與 hold

FramingEngine 的動態 zoom target 不會直接跳到 camera：

- tracking 時以 `zoom_ramp_per_second` 逐步接近 target；
- target lost 後先保持最後倍率 `zoom_hold_seconds`；
- hold 結束後以相同 ramp 回到 wide target；
- uncertainty freeze 時倍率完全保持，不執行 zoom in、zoom out 或 lost return。

預設 zoom ramp 為每秒 0.8x、hold 1 秒、return target 1x。

## Uncertainty freeze

下列任一條件會輸出 `UNCERTAINTY_FREEZE`：

- `motor_safe_to_track` 為 false；
- ReID confidence 為 low、candidate、lost 或 searching；
- identity decision 未接受；
- identity uncertainty score 低於 0.65。

Freeze command 會將 `target_locked=false`、yaw/pitch 歸零並保持目前 zoom。UI 不再提前繞過 policy，而是仍送出這筆明確 safety command，確保 freeze 原因可由 telemetry 與 wire log 稽核。

## Output contract

`CameraControlDecision` 輸出：

- filtered `error_x/error_y`；
- yaw/pitch velocity 與 acceleration；
- raw zoom target 與 ramped zoom output；
- axis active flags、target lock、frozen flag；
- uncertainty score 與 reason code。

Reason codes：`TRACKING`、`DEAD_ZONE`、`HYSTERESIS_TRACKING`、`TARGET_LOST_ZOOM_HOLD`、`TARGET_LOST_ZOOM_RETURN`、`UNCERTAINTY_FREEZE`。

Bootstrap 建立唯一 policy instance，注入 TrackingWebSocketServer/ControlPolicy 並由 application container 公開。停止或解除 motor arm 時會 reset state，避免前一來源的 velocity 或 zoom history 污染下一段 tracking session。
