"""Main pilot run loop.

For every item: each small model runs DIRECT, RAG, REASON; the escalation
model runs ESCALATE (= DIRECT prompt). Per-request energy is metered and each
generation is appended to outputs/<run_id>/generations.jsonl (append-only;
re-running the same run_id skips already-completed requests).

Usage:
    python -m src.run_pilot --config config.yaml --backend dummy
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .conditions import SMALL_MODEL_CONDITIONS, build_prompt
from .energy import get_meter
from .models import DecodeConfig, get_backend
from .retrieval import get_retriever
from .schema import load_items


def _append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _completed_keys(path: Path) -> set[tuple]:
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            done.add((r["item_id"], r["model"], r["condition"]))
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--backend", help="override config backend (dummy|vllm|hf)")
    ap.add_argument("--run-id", help="reuse to resume; default = timestamp")
    ap.add_argument("--items", help="override items file from config")
    ap.add_argument("--limit", type=int, help="run only the first N items (smoke test)")
    ap.add_argument("--models", help="comma-separated substring filter of model "
                    "names to run (use one model per invocation on GPU so vLLM "
                    "releases memory between models; same --run-id accumulates)")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    backend_kind = args.backend or cfg["backend"]
    items = load_items(args.items or cfg["paths"]["items"])
    if args.limit:
        items = items[: args.limit]

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(cfg["paths"]["outputs"]) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    gen_path = out_dir / "generations.jsonl"
    done = _completed_keys(gen_path)

    meter = get_meter(cfg["energy"]["mode"] if backend_kind != "dummy" else "dummy",
                      device_index=cfg["energy"].get("device_index", 0),
                      poll_hz=cfg["energy"].get("poll_hz", 10))
    info = meter.device_info()
    idle_w = meter.idle_baseline(cfg["energy"].get("idle_seconds", 10))

    meta = {
        "run_id": run_id,
        "started": datetime.now(timezone.utc).isoformat(),
        "backend": backend_kind,
        "energy_method": meter.method,
        "energy_note": "GPU-only measurement (excludes CPU/DRAM/cooling) — pilot grade",
        "device": info.name,
        "driver": info.driver,
        "power_limit_w": info.power_limit_w,
        "idle_baseline_w": round(idle_w, 2),
        "config": cfg,
        "n_items": len(items),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"run {run_id}: {len(items)} items, backend={backend_kind}, "
          f"energy={meter.method}, device={info.name}, idle={idle_w:.1f} W")

    decode = DecodeConfig(**cfg["decode"])
    system_prompt = cfg["system_prompt"]
    retriever = get_retriever(cfg["paths"]["corpus"],
                              dense=cfg["retrieval"].get("dense", False),
                              dense_model=cfg["retrieval"].get("dense_model", ""))
    top_k = cfg["retrieval"].get("top_k", 5)

    # (model_name, conditions) job list: small models x 3 conditions + 70B x ESCALATE
    jobs = [(m, SMALL_MODEL_CONDITIONS) for m in cfg["models"]["small"]]
    jobs.append((cfg["models"]["escalate"], ("ESCALATE",)))
    if args.models:
        pats = [p.strip().lower() for p in args.models.split(",") if p.strip()]
        jobs = [(m, c) for m, c in jobs if any(p in m.lower() for p in pats)]
        if not jobs:
            print(f"no configured model matches --models '{args.models}'")
            return 1

    total = skipped = 0
    for model_name, conds in jobs:
        # Per-model backend override (e.g. 70B via hosted API on small-GPU
        # setups). Ignored in dummy mode so laptop pipeline tests stay offline.
        override = cfg.get("model_backends", {}).get(model_name)
        if override and backend_kind != "dummy":
            kind = override["backend"]
            served_name = override.get("model", model_name)
            kw = {k: v for k, v in override.items() if k not in ("backend", "model")}
            backend = get_backend(kind, served_name, decode, **kw)
        else:
            kind = backend_kind
            vllm_kw = cfg.get("vllm_kwargs", {}).get(model_name, {}) if kind == "vllm" else {}
            backend = get_backend(kind, model_name, decode, **vllm_kw)
        metered = kind != "api"  # remote calls: local GPU joules are meaningless
        for item in items:
            chunks = None
            for cond in conds:
                key = (item["id"], model_name, cond)
                if key in done:
                    skipped += 1
                    continue
                if cond == "RAG" and chunks is None:
                    chunks = retriever.search(item["question"], top_k)
                prompt = build_prompt(cond, item["question"],
                                      chunks if cond == "RAG" else None)
                if metered:
                    with meter.measure() as m:
                        result = backend.generate(system_prompt, prompt)
                    energy_j, energy_method, duration_s = round(m.joules, 4), m.method, round(m.seconds, 4)
                else:
                    t0 = time.monotonic()
                    result = backend.generate(system_prompt, prompt)
                    energy_j, energy_method = None, "unmeasured_api"
                    duration_s = round(time.monotonic() - t0, 4)
                _append_jsonl(gen_path, {
                    "run_id": run_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "item_id": item["id"],
                    "category": item["category"],
                    "language": item["language"],
                    "model": model_name,
                    "condition": cond,
                    "prompt": prompt,
                    "response": result.text,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "energy_j": energy_j,
                    "energy_method": energy_method,
                    "duration_s": duration_s,
                    "idle_baseline_w": round(idle_w, 2),
                    "retrieved": [
                        {k: c[k] for k in ("doc_id", "chunk_id", "score")}
                        for c in (chunks or [])
                    ] if cond == "RAG" else None,
                })
                total += 1
        print(f"  {model_name}: done ({total} generations so far)")

    print(f"wrote {total} generations ({skipped} already present) -> {gen_path}")
    print(f"next: python -m src.extract --run {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
