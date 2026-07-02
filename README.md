# AutoCamTracker

AutoCamTracker 是一個把 iPhone / webcam / 影片 / 螢幕畫面變成「自動攝影助理」的車輛追蹤專案。桌面端負責車輛偵測、單一目標追蹤、GID 長期身份管理與數位構圖；iPhone 端負責傳送相機畫面，並透過 DockKit 控制實體雲台與相機變焦。

## 專案目標

這個專案的目標是讓拍攝賽車、車聚、測試影片或其他車輛動態場景時，可以用 AI 自動鎖定指定車輛，讓畫面維持在可用的構圖範圍內，並在短暫遮擋、切鏡或 tracker 掉 ID 時盡量找回同一台車。

長期方向包括：

- 降低 iPhone 串流到桌面辨識再回控雲台的延遲。
- 提高指定車輛在遮擋、遠近變化、光影變化下的 GID 重新辨識穩定度。
- 讓使用者可以用簡單的 UI 選車、建立身份、找回身份與累積 Master features。
- 讓 DockKit 雲台與 iPhone 實體變焦能跟桌面端追蹤結果同步工作。

## 目前做到的項目

- 桌面版 Python / Tkinter app，可從 `webcam`、影片檔、影片網址、螢幕區域或 iPhone 串流讀取畫面。
- YOLO 車輛偵測與 tracking profile：
  - High FPS profile 預設使用 `model/yolo26n.pt` + `bytetrack`，目標是降低 iPhone 30 FPS 串流延遲。
  - Balanced ID profile 可切換到 `model/yolo26s.pt` + `botsort`，搭配 ReID 做較穩定的身份追蹤。
- GID / LID 身份系統：
  - `GID` 是使用者建立的長期車輛身份。
  - `LID` 是 tracker 當下產生的短期 local track id。
  - 可以點選 bbox 建立 GID、把 bbox 綁定到既有 GID，或用 `Find GID` 從目前畫面找回指定車輛。
- Master feature gallery：
  - 支援手動加入單張 feature。
  - 支援自動採樣 feature，並用 crop 品質、class 與 ReID 分數做防污染檢查。
  - 偵測到切鏡後會停止自動採樣，避免把不同場景的錯車寫入同一個 GID。
- 數位構圖與失追處理：
  - After 畫面會依選定車輛重新置中與變焦。
  - target lost 時會短暫保留 zoom，再平滑退回 wide。
  - GID 失追時有短期 coasting，降低畫面瞬間跳動。
- iPhone / DockKit 整合：
  - iOS App 可透過 WebSocket 傳 JPEG 相機畫面到桌面端。
  - 桌面端會回傳 tracking command 與 `zoom_factor`。
  - iOS 端會關閉 DockKit System Tracking，改由桌面 AI 辨識結果控制雲台。
  - 支援相對 Home / Return Home、動態 smoothing 與前饋控制。
- 測試與驗證：
  - Python tests 覆蓋 tracking server、GID loss benchmark、performance evaluation、track shot plan 與桌面最佳化邏輯。
  - iOS Swift tests 覆蓋雲台速度計算與 tracking command parsing。

## 主要目錄

- `src/autocamtracker/`：桌面端主要程式碼。
- `ios/DockKitTester/`：iPhone / DockKit 測試 App。
- `tests/`：Python 測試。
- `evaluation/`：GID loss benchmark 設定。
- `tools/`：macOS 啟動用 command 檔。
- `code/model/`：本機模型與 tracker 相關資源；大型模型權重不建議直接放進一般 Git history。
