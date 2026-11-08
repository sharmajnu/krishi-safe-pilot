"""Embryonic Pareto figure: unsafe-rate vs mean joules, one marker per
(model, condition), conditions connected per model. Pooled across languages
plus one panel per language.

Usage:
    python -m src.plots outputs/<run_id>/
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from .score import aggregate, load_run

CONDITION_ORDER = ["DIRECT", "RAG", "REASON", "ESCALATE"]


def _series(rows: list[dict], language: str | None) -> dict[str, list[tuple]]:
    """model -> [(joules, unsafe_rate, condition)] in condition order."""
    per_model: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if language and r["language"] != language:
            continue
        per_model[r["model"]][r["condition"]].append(r)
    out: dict[str, list[tuple]] = {}
    for model, conds in per_model.items():
        pts = []
        for cond in CONDITION_ORDER:
            rs = [r for r in conds.get(cond, [])
                  if r["mean_joules"] is not None and r["unsafe_tail_rate"] is not None]
            if rs:
                j = sum(r["mean_joules"] * r["n"] for r in rs) / sum(r["n"] for r in rs)
                u = sum(r["unsafe_tail_rate"] * r["n"] for r in rs) / sum(r["n"] for r in rs)
                pts.append((j, u, cond))
        if pts:
            out[model] = pts
    return out


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print(__doc__)
        return 2
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    run_dir = Path(argv[0])
    verdicts, energy, meta = load_run(run_dir)
    rows = aggregate(verdicts, energy)
    escalate_model = meta["config"]["models"]["escalate"]

    languages = [None] + sorted({r["language"] for r in rows})
    fig, axes = plt.subplots(1, len(languages), figsize=(5 * len(languages), 4.5),
                             squeeze=False)
    for ax, lang in zip(axes[0], languages):
        series = _series(rows, lang)
        # ESCALATE points belong on every small model's trajectory
        esc = series.pop(escalate_model, [])
        for model, pts in sorted(series.items()):
            allpts = pts + esc
            xs, ys = [p[0] for p in allpts], [p[1] for p in allpts]
            ax.plot(xs, ys, marker="o", label=model.split("/")[-1], alpha=0.8)
            for x, y, cond in allpts:
                ax.annotate(cond, (x, y), fontsize=7, xytext=(3, 3),
                            textcoords="offset points")
        ax.set_xlabel("mean joules / query (GPU-only)")
        ax.set_ylabel("unsafe rate (tail strata A-D, F)")
        ax.set_title("pooled" if lang is None else f"language: {lang}")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    fig.suptitle(f"KRISHI-SAFE pilot — unsafe vs energy (run {meta['run_id']})")
    fig.tight_layout()
    out = run_dir / "unsafe_vs_joules.png"
    fig.savefig(out, dpi=150)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
