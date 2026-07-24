# Golden Dataset v1

This directory is the versioned input contract for V2.2 model comparisons.
The included JSONL is a format example, not a validity claim and not a real
accuracy dataset. Replace the disabled manifest sequence with user-owned,
annotated footage before publishing scores.

Each annotation line uses the existing `ReplayFrame` format:

```json
{
  "frame_index": 0,
  "capture_timestamp_ms": 0.0,
  "ground_truth": [
    {
      "bbox": [100, 80, 300, 220],
      "class_id": 2,
      "identity_id": 7
    }
  ]
}
```

Rules:

1. Annotate the exact decoded source frames used by the benchmark.
2. Keep a complete race or recording session in only one split.
3. Use a stable identity ID for the same physical vehicle.
4. Record invisible/absent periods explicitly in scenario metadata.
5. Never use model predictions as ground truth.
6. Freeze the manifest and increment `dataset_version` when annotations change.

The Benchmark Center currently accepts one video and one JSONL annotation file.
The headless `model-benchmark` command uses the same input and runs up to five
models sequentially.
