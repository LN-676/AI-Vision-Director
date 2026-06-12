# AutoCamTracker V1.2

AutoCamTracker 是一個以影片、螢幕區域或 webcam 作為輸入的車輛偵測與追蹤工具。V1.2 版本在 V1.1 的可操作桌面原型上，加入 Identity DB、車輛全域 ID、ReID embedding gallery，以及可選的 BoT-SORT ReID tracker。

## 功能簡述

- 支援 webcam、影片檔、螢幕區域三種輸入來源。
- 支援 YOLO 模型偵測車輛，並顯示 bbox、track id、confidence。
- 可在 Before 畫面直接點選 bbox，或使用 Auto Track 選擇追蹤車輛。
- Identity DB 會記錄車輛全域 ID、觀測次數、重複寫入次數與最後追蹤資訊。
- 可點選 Identity DB 車輛列，讓系統用資料庫特徵反向比對目前畫面並重新追蹤該車。
- 支援雙擊 GID 欄位自訂車輛 ID 顯示名稱。
- 支援 `botsort_reid` tracker，並在 Identity DB 層使用 ReID embedding gallery 改善重新辨識。
- After 畫面會依追蹤目標做數位變焦與置中構圖。
- 支援影片播放速度調整與時間軸拖曳。
- Before / After 畫面會跟隨視窗等比縮放。

## 區塊分工

- `code/V1/app.py`：Tkinter UI、控制列、Before / After 顯示、時間軸、使用者互動。
- `code/V1/video_detector.py`：影片/webcam/螢幕來源讀取、YOLO 模型載入、偵測與追蹤器串接。
- `code/V1/detection_store.py`：保存目前偵測結果、track 歷史與候選車輛排序。
- `code/V1/target_tracker.py`：單一目標選取、lost 狀態與追蹤狀態管理。
- `code/V1/reframer.py`：依目標 bbox 建立 crop window，輸出追蹤構圖畫面。
- `code/V1/tracker_adapter.py`：外部追蹤器 adapter。
- `code/V1/vehicle_identity_store.py`：SQLite Identity DB、車輛 observation 與 ReID gallery matching。
- `code/V1/reid_embedding.py`：Ultralytics ReID encoder 包裝，用於抽取車輛 appearance embedding。
- `code/V1/trackers/botsort_reid.yaml`：啟用 ReID 的 BoT-SORT tracker 設定。
- `code/model/`：YOLO 模型與外部 tracker 程式資料。
- `management/AutoCamTracker_Development/`：開發規格、技術報告與版本變更紀錄。

## 使用方式

建議從專案根目錄執行：

```bash
.venv/bin/python run_v1_app.py
```

基本流程：

1. 在 Source 區選擇 `webcam`、`video_file` 或 `screen_region`。
2. 若使用影片，按 `Browse Video` 選擇檔案。
3. 在 Tracking 區選擇模型、tracker 與 framing 模式。
4. 按 `Start` 開始偵測。
5. 在 Before 畫面點選車輛 bbox，或按 `Auto Track`。
6. 在 Identity DB 中查看已記錄車輛；點選資料列可嘗試用 DB 特徵找回目前畫面中的同一台車。
7. 在 After 畫面確認追蹤構圖結果。

## V1.2 注意事項

- V1.2 仍以單一車輛追蹤與互動式重新辨識為主。
- `LID` 是 YOLO / tracker 的短期本地 ID；`GID` 是 AutoCamTracker 的長期車輛身份。
- ReID gallery 需要累積多筆 observation 才會穩定；只用單張小 crop 重新辨識仍可能不可靠。
- `botsort_reid` 第一次使用時需要 `yolo26n-reid.onnx`，Ultralytics 會嘗試自動下載；大型模型檔仍不納入 git。

---

# AutoCamTracker V1.2 English

AutoCamTracker is a vehicle detection and tracking desktop tool that can use a video file, a selected screen region, or a webcam as the input source. The V1.2 release adds an Identity DB, global vehicle IDs, ReID embedding gallery matching, and an optional BoT-SORT ReID tracker on top of the V1.1 desktop workflow.

## Feature Overview

- Supports three input sources: webcam, video file, and screen region.
- Uses YOLO models to detect vehicles and display bbox, track id, and confidence.
- Allows target selection by clicking a bbox in the Before view or by using Auto Track.
- Records global vehicle IDs, observations, repeated writes, and latest tracker metadata in the Identity DB.
- Allows selecting an Identity DB row to match that stored vehicle back against the current frame.
- Allows editing the displayed GID label by double-clicking the GID column.
- Supports `botsort_reid` and ReID embedding gallery matching for stronger re-identification.
- The After view digitally zooms and centers the frame based on the selected target.
- Supports video playback speed control and timeline seeking.
- The Before / After views scale proportionally with the application window.

## Project Structure

- `code/V1/app.py`: Tkinter UI, control bar, Before / After display, timeline, and user interaction.
- `code/V1/video_detector.py`: Video, webcam, and screen input handling, YOLO model loading, detection, and tracker integration.
- `code/V1/detection_store.py`: Stores current detections, track history, and candidate vehicle ranking.
- `code/V1/target_tracker.py`: Single target selection, lost state handling, and tracking state management.
- `code/V1/reframer.py`: Builds the crop window from the target bbox and produces the tracking output frame.
- `code/V1/tracker_adapter.py`: Adapter for external trackers.
- `code/V1/vehicle_identity_store.py`: SQLite Identity DB, vehicle observations, and ReID gallery matching.
- `code/V1/reid_embedding.py`: Wrapper around the Ultralytics ReID encoder.
- `code/V1/trackers/botsort_reid.yaml`: BoT-SORT tracker config with ReID enabled.
- `code/model/`: YOLO model and external tracker resources.
- `management/AutoCamTracker_Development/`: Development specs, technical reports, and version change logs.

## How To Run

Run from the project root:

```bash
.venv/bin/python run_v1_app.py
```

Basic workflow:

1. Select `webcam`, `video_file`, or `screen_region` in the Source section.
2. If using a video file, click `Browse Video` and choose a file.
3. Select the model, tracker, and framing mode in the Tracking section.
4. Click `Start` to begin detection.
5. Click a vehicle bbox in the Before view, or click `Auto Track`.
6. Use the Identity DB to inspect recorded vehicles; click a row to match that stored vehicle against the current frame.
7. Check the reframed tracking result in the After view.

## V1.2 Notes

- V1.2 still focuses on single-vehicle tracking and interactive re-identification.
- `LID` is the short-term tracker ID; `GID` is AutoCamTracker's long-lived vehicle identity.
- ReID gallery matching becomes more reliable after multiple observations are collected for a vehicle.
- `botsort_reid` needs `yolo26n-reid.onnx` on first use; large model files remain excluded from git.
