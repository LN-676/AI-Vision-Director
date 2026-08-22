# V2.2.1 Benchmark Center

## Reproducibility boundary

Model comparisons run sequentially against the exact same decoded video and
ground-truth JSONL. Running several desktop processes at once is intentionally
not part of the protocol because CPU, GPU, decoder, and memory contention would
change latency and throughput.

The versioned Golden Dataset contract lives under `evaluation/golden/`.
Changing footage or annotations requires a new `dataset_version`. A complete
race or recording session must remain in one train/validation/test split.

## Profiles

- **Quick Auto · proxy**: requires only a video. For each selected Detection ×
  ReID pair it enrolls a frozen, quality-gated feature gallery, excludes those
  enrollment frames from scoring, runs one to five measured rounds, detects
  hard cuts, and reports per-shot consistency plus real measured throughput.
  These proxy values are never labeled mAP, HOTA, Rank-1, or false-reacquire
  accuracy because they have no human-verified identity truth.
- **Vision Core**: Detection, Tracking, and Realtime axes. This profile is
  produced by `model-benchmark` from a video, ground truth, model list, and
  tracker choice.
- **Full Pipeline**: adds Identity, Framing, and Control. It consumes the
  existing `OfflineReplayReport` with ReID and closed-loop control observations.
- **Live capture**: records source video and observations for iPhone/DockKit
  sessions. Its manifest is marked `ground_truth_status=pending`; model output
  is never accepted as ground truth.

Profiles and dataset versions must match before scores are treated as directly
comparable.

Quick Auto defaults to 50 feature images and three measured rounds. A duration
of zero processes the full file. A fixed live stream must first be recorded so
every model pair sees identical frames; running pairs directly against a
changing live source is not a valid comparison.

For iPhone or another live source, use **Track Page → Record**, stop after the
desired duration, then choose the generated `source.mp4` in Benchmark Center.
The configured Benchmark duration applies to both an ordinary file and this
recorded stream.

The detailed result metadata contains every measured round and an aggregate for
each automatically detected shot. A hard cut identifies a shot boundary, not a
physical camera identity. Camera A/B/C labels still require source metadata or
operator confirmation.

## Score

The UI displays a ratio chart and a maximum score of 1,000,000. The score is
the average of the available normalized axes, with an explicit coverage value:

- Detection: mAP50-95, Precision, Recall.
- Tracking: HOTA, IDF1, MOTA.
- Identity: Rank-1, reacquire success, inverse false-reacquire rate.
- Framing: inverse target-out-of-frame ratio.
- Control: inverse jitter, overshoot, and settling-time budgets.
- Realtime: FPS against 30 FPS, inverse P95 latency against 150 ms, and inverse
  dropped-frame rate.

The score is intended for comparing the same benchmark profile and dataset,
not for comparison with external products. A failed safety gate forces the
score to zero. Missing axes are not hidden: the UI reports coverage next to
every score.

## Standard evaluator bridge

`standard_formats.py` exports:

- COCO ground-truth and prediction JSON for official `COCOeval`.
- MOTChallenge ground-truth and tracker text for official TrackEval.

The built-in evaluator remains useful for deterministic unit and regression
tests. Published or portfolio numbers should be verified with the official
COCO and TrackEval tools.

## Headless runner

```bash
model-benchmark \
  --video evaluation/golden/videos/race-a.mp4 \
  --annotations evaluation/golden/annotations/race-a.jsonl \
  --model models/detection/yolo26n.pt \
  --model models/detection/yolo26s.pt \
  --tracker botsort \
  --dataset-version race-golden-v1 \
  --output outputs/benchmarks/model-comparison.json
```

One to five models may be supplied. The same JSON can be imported into the
Benchmark Center for visual comparison.

## Future plug-in template

The stable extension point is `VisionBenchmarkRequest -> ModelBenchmarkResult`.
A future automatic model-import template should implement these steps:

1. validate file type and model metadata;
2. create an isolated model adapter;
3. perform warm-up;
4. run the frozen dataset sequentially;
5. export native predictions plus COCO/MOT interchange files;
6. calculate a profile-specific score and coverage;
7. store the model hash, runtime, hardware, settings, dataset version, and Git
   commit with the result;
8. reject comparisons whose profile or dataset version differs.

Score weights remain versioned policy and should not be changed until a real
Golden Dataset and product acceptance thresholds have been agreed.
