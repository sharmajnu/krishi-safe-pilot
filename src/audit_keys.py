"""Interactive answer-key audit: verify each unique question's key against
its verbatim source span, flip verify flags, log disagreements, and print
the precision statistics for the paper.

Verifying a key covers all four language variants of that question (the key
is shared); translation_verified flags are a separate, per-item concern.

Usage:
    python -m src.audit_keys --items data/items.jsonl           # all 50
    python -m src.audit_keys --items data/items.jsonl --limit 20
Keys: y = key matches source span   n = mismatch (asks for a note)
      o = open source URL in browser   s = skip   q = quit (progress saved)
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import date
from pathlib import Path

LOG = Path("data/sources/key_audit_log.jsonl")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--items", default="data/items.jsonl")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)

    path = Path(args.items)
    items = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_q: dict[str, list[dict]] = {}
    for it in items:
        by_q.setdefault(it["id"].rsplit("-", 1)[0], []).append(it)

    pending = [q for q, variants in sorted(by_q.items()) if variants[0]["verify"]]
    done_before = len(by_q) - len(pending)
    if args.limit:
        pending = pending[: args.limit]
    print(f"{len(by_q)} unique questions; {done_before} already verified, "
          f"{len(pending)} to audit now.\n")

    audited = mismatches = 0
    for qi, q in enumerate(pending, 1):
        en = next(v for v in by_q[q] if v["language"] == "en")
        k = en["answer_key"]
        print("=" * 72)
        print(f"[{qi}/{len(pending)}] {q} (stratum {en['category']})")
        print(f"Q: {en['question']}")
        print(f"KEY: {json.dumps(k, ensure_ascii=False)}")
        print(f"SRC: {en['source']['url']}")
        print(f"SPAN: {en['source']['span']}")
        while True:
            ans = input("[y]=matches  [n]=mismatch  [o]=open URL  [s]=skip  [q]=quit > ").strip().lower()
            if ans == "o":
                webbrowser.open(en["source"]["url"])
                continue
            break
        if ans == "q":
            break
        if ans == "s":
            continue
        audited += 1
        verdict = "match"
        note = ""
        if ans == "n":
            mismatches += 1
            verdict = "mismatch"
            note = input("  note (what is wrong): ").strip()
        else:
            for v in by_q[q]:
                v["verify"] = False
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"date": str(date.today()), "question": q,
                                "verdict": verdict, "note": note},
                               ensure_ascii=False) + "\n")

    path.write_text("\n".join(json.dumps(v, ensure_ascii=False)
                              for q in sorted(by_q) for v in by_q[q]) + "\n",
                    encoding="utf-8")

    total_logged = audited + 0
    print("\n" + "=" * 72)
    print(f"Audited this session: {audited}; mismatches: {mismatches}")
    all_logs = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()] if LOG.exists() else []
    n, m = len(all_logs), sum(1 for l in all_logs if l["verdict"] == "mismatch")
    if n:
        print(f"CUMULATIVE for the paper: {n} keys audited, {n-m} agreed "
              f"({(n-m)/n:.1%} agreement), {m} mismatches (see {LOG})")
        print("Paper sentence: 'A human audit of {}/50 answer keys against the "
              "snapshotted sources found {} discrepancies ({:.0f}\\% agreement).'"
              .format(n, m, 100*(n-m)/n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
