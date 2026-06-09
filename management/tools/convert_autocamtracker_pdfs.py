#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass
class SourceDoc:
    path: Path
    title: str
    slug: str


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(f"\n\n## Page {index}\n\n{text.strip()}\n")
    return "\n".join(pages).strip() + "\n"


def normalize_title(path: Path) -> str:
    title = path.stem.replace("_", " ").strip()
    return re.sub(r"\s+", " ", title)


def slugify(path: Path) -> str:
    slug = path.stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def markdown_for(doc: SourceDoc, text: str) -> str:
    return (
        f"# {doc.title}\n\n"
        f"Source PDF: `{doc.path.name}`\n\n"
        "This file was generated from the PDF development log so the content can be "
        "tracked in Git and referenced by GitHub Issues/Projects.\n\n"
        f"{text}"
    )


def detect_items(text: str, source: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[\-*•]\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        lowered = line.lower()
        if re.fullmatch(r"Page \d+", line):
            continue
        has_action_marker = any(
            marker in lowered
            for marker in (
                "todo",
                "to-do",
                "task",
                "next",
                "bug",
                "fix",
                "issue",
                "current iteration",
                "iteration",
                "phase",
                "milestone",
                "待辦",
                "任務",
                "修正",
                "問題",
                "下一步",
                "迭代",
                "階段",
            )
        )
        if not has_action_marker:
            continue
        title = re.sub(r"^#+\s*", "", line).strip(" :-")
        if len(title) < 4 or title in seen:
            continue
        seen.add(title)
        items.append(
            {
                "Title": title[:240],
                "Body": f"Source: {source}\n\nImported from the PDF development log.",
                "Status": "Todo",
                "Iteration": "@current",
                "Labels": "autocamtracker, imported",
            }
        )
    return items


def write_outputs(docs: list[SourceDoc], out_dir: Path) -> None:
    docs_dir = out_dir / "docs"
    import_dir = out_dir / "github-project-import"
    docs_dir.mkdir(parents=True, exist_ok=True)
    import_dir.mkdir(parents=True, exist_ok=True)

    all_items: list[dict[str, str]] = []
    for doc in docs:
        text = extract_text(doc.path)
        (docs_dir / f"{doc.slug}.md").write_text(markdown_for(doc, text), encoding="utf-8")
        (docs_dir / f"{doc.slug}.txt").write_text(text, encoding="utf-8")
        all_items.extend(detect_items(text, doc.path.name))

    if not all_items:
        all_items = [
            {
                "Title": doc.title,
                "Body": f"Source: {doc.path.name}\n\nReview and split this development log into GitHub Issues.",
                "Status": "Todo",
                "Iteration": "@current",
                "Labels": "autocamtracker, imported",
            }
            for doc in docs
        ]

    curated_items = [
        {
            "Title": "Initialize GitHub repository and branch workflow",
            "Body": "建立 GitHub repository，設定 main / develop / feature branch 規範，並讓所有功能透過 PR 合併。\n\nSource: AutoCamTracker_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, github",
        },
        {
            "Title": "Scaffold C++20 CMake Qt 6 application",
            "Body": "建立 AutoCamTracker C++ 專案骨架，包含 CMake、Qt 6 MainWindow、基本資料夾結構與 README/build guide。\n\nSource: AutoCamTracker_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, frontend",
        },
        {
            "Title": "Build LiveViewWidget and vehicle panel with mock data",
            "Body": "前端建立 Live View、Detected Vehicles panel、StatusBarWidget，先用假資料顯示 bbox、縮圖與 Start / Stop / Reset 操作。\n\nSource: AutoCamTracker_V1_Division_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, frontend",
        },
        {
            "Title": "Define frontend-backend UI data contracts",
            "Body": "約定 UiDetectionItem 與 UiFrameData，包含 raw/display frame、detections、selected target、FPS、inference time、errorX/errorY 與 tracking status。\n\nSource: AutoCamTracker_V1_Division_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, interface",
        },
        {
            "Title": "Implement video source interfaces",
            "Body": "後端建立 IVideoSource、MacCameraSource 與 VideoFileSource，支援解析度/FPS 設定，並處理鏡頭開啟失敗。\n\nSource: AutoCamTracker_V1_Division_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, backend",
        },
        {
            "Title": "Create YOLO detector interface and ONNX Runtime path",
            "Body": "準備 YOLOv11 / YOLO11 ONNX 模型載入流程，建立 YoloDetector interface，完成 preprocessing、inference、postprocessing 的實作路徑。\n\nSource: AutoCamTracker_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, ai",
        },
        {
            "Title": "Implement thumbnail cropping for detections",
            "Body": "根據 bbox 裁切 vehicle thumbnail，避免 bbox 超出畫面邊界，統一縮圖尺寸並綁定 detection id。\n\nSource: AutoCamTracker_V1_Division_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, backend",
        },
        {
            "Title": "Implement target selection and SimpleTracker",
            "Body": "建立 TargetSelector 與 SimpleTracker，支援 selectTarget、unlockTarget、resetTracking，並用中心距離維持單一目標追蹤與 lost 狀態。\n\nSource: AutoCamTracker_V1_Division_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, tracking",
        },
        {
            "Title": "Implement FramingController error calculation",
            "Body": "計算 frame center、target center、error_x/error_y、normalized error 與 dead zone，並輸出 virtual pan/tilt command 供 V2 延伸。\n\nSource: AutoCamTracker_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, tracking",
        },
        {
            "Title": "Implement DigitalCropController",
            "Body": "根據 error_x/error_y 移動 crop window，加入 smoothing，限制 crop window 不超出原始 frame，輸出置中的 cropped frame。\n\nSource: AutoCamTracker_V1_Division_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, tracking",
        },
        {
            "Title": "Add config and logging",
            "Body": "建立 default_config.json 與 ConfigManager，加入 spdlog 或等效 logging，記錄 camera、YOLO、tracking、crop boundary、FPS 與 inference time。\n\nSource: AutoCamTracker_V1_Division_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, backend",
        },
        {
            "Title": "Integrate V1 demo pipeline",
            "Body": "整合 camera、detection、thumbnail、target selection、tracking、framing、digital crop 與 UI，完成可展示的 V1 demo pipeline。\n\nSource: AutoCamTracker_Development_Log.pdf",
            "Status": "Todo",
            "Iteration": "@current",
            "Labels": "autocamtracker, current-iteration, integration",
        },
    ]

    with (import_dir / "current-iteration-items.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["Title", "Body", "Status", "Iteration", "Labels"])
        writer.writeheader()
        writer.writerows(curated_items)

    (import_dir / "README.md").write_text(
        "# GitHub Project Import\n\n"
        "Use `current-iteration-items.csv` as the staging file for GitHub Project items.\n\n"
        "GitHub Projects does not read a Git commit as Project rows automatically. "
        "Create GitHub Issues from these rows, add the issues to the Project, then set "
        "the Project iteration field to the current iteration. `@current` is a local "
        "placeholder for that step, not a GitHub CSV magic value.\n\n"
        "Recommended issue fields:\n\n"
        "- `Title`: issue title\n"
        "- `Body`: issue body\n"
        "- `Status`: Project status, usually `Todo`\n"
        "- `Iteration`: set this to the Project's current iteration after import\n"
        "- `Labels`: comma-separated labels to apply to the issue\n",
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: convert_autocamtracker_pdfs.py PDF [PDF ...]", file=sys.stderr)
        return 2
    docs = [
        SourceDoc(path=Path(arg).expanduser(), title=normalize_title(Path(arg)), slug=slugify(Path(arg)))
        for arg in sys.argv[1:]
    ]
    write_outputs(docs, Path.cwd())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
