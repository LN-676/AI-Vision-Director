# Phase 13：Camera Calibration 與 GMC

Phase 13 建立兩個可獨立測試、由 composition root 組裝的 vision subsystem：Camera Calibration 管理鏡頭模型與去畸變；Global Motion Compensation（GMC）估計相鄰影格的背景全域運動。GMC 的結果是明確的 pipeline 輸出，不會在本階段暗中修改 detection、tracking 或 identity 決策。

## Camera Calibration

`CameraCalibration` profile 保存：

- profile ID、camera name、校正解析度與 pinhole/fisheye lens model；
- `fx`、`fy`、`cx`、`cy` camera intrinsics；
- distortion coefficients；
- RMS reprojection error、有效 chessboard view 數、校正時間與來源。

`CameraCalibrationStore` 使用 schema-versioned JSON 與 atomic replace 保存多個具名 profile。讀取時會拒絕未知 schema；寫入相同 ID 代表更新該 profile。`CameraCalibrationSubsystem.activate()` 控制唯一的 active profile，設為 `None` 即停用校正。

OpenCV backend 以多張 chessboard 影格執行 corner refinement 和 `calibrateCamera`。套用 profile 時，intrinsics 會依目前影格寬高分別縮放，再執行 pinhole 或 fisheye undistortion。沒有 active profile 時會原樣傳回影格。

典型呼叫：

```python
profile = app.camera_calibration.calibrate_chessboard(
    frames,
    profile_id="iphone-main",
    camera_name="iPhone main camera",
    board_size=(9, 6),
    square_size=0.024,
    min_views=8,
)
app.camera_calibration.activate(profile.profile_id)
```

## Global Motion Compensation

`GlobalMotionCompensator` 保存前一張影格及其 detection exclusions，流程如下：

1. 若存在 active calibration，先對影格去畸變。
2. 將前一影格的車輛 bbox 加 padding 後遮罩，避免把目標自身運動當成 camera motion。
3. 以 Shi-Tomasi features 與 pyramidal Lucas-Kanade optical flow 建立背景對應點。
4. 再排除落入目前 detection bbox 的點。
5. 以 RANSAC partial affine model 估計 previous-to-current transform。
6. 依 inlier ratio、translation、rotation、scale limits 判定是否可靠。

每個 `GlobalMotionEstimate` 都輸出 transform、反向 compensation transform、平移、旋轉、尺度、tracked/inlier 數、inlier ratio、residual、可靠性、reason code 與 calibration profile ID。下游若要把目前座標補償回前一影格，可使用 `compensation_transform` 或 `compensate_point()`。

Reason codes：

- `INITIALIZING`：尚無相鄰影格。
- `ESTIMATED`：估計通過品質閘門。
- `CAMERA_CUT_RESET`：scene cut 後清除 temporal state。
- `FRAME_SHAPE_CHANGED`：解析度改變，重新建立 temporal pair。
- `INSUFFICIENT_FEATURES`、`OPTICAL_FLOW_FAILED`、`AFFINE_ESTIMATION_FAILED`：估計資料不足或 backend 失敗。
- `LOW_INLIER_RATIO`、`EXCESSIVE_TRANSFORM`：得到 transform，但未通過可信度限制。

## Pipeline 與輸出邊界

Bootstrap 建立單一 calibration subsystem，並注入 GMC；`TrackingApplication` 同時公開 `camera_calibration` 與 `gmc`。Pipeline 在 scene-cut 判定後執行 GMC，camera cut 會先 reset GMC temporal state，避免跨鏡頭切換估計。

每個 `FrameData` 與 telemetry/desktop diagnostics 包含：

- `global_motion`
- `camera_calibration_profile_id`
- `gmc_time_ms`

不可靠的估計仍會輸出其量測與 reason code，讓下游自行決定降級策略；只有 `reliable=True` 的結果應用於運動補償。
