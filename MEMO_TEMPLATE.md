# KRISHI-SAFE Pilot Memo — GO/NO-GO

Run: `<run_id>` · Date: `<date>` · Hardware: `<GPU, driver, power limit>` ·
Energy method: `<nvml|poll>` (GPU-only measurement — excludes CPU/DRAM/cooling)

## 1. Decision

**`<GO | PIVOT | NO-GO>`** — paste the decision block from
`outputs/<run_id>/report.md` verbatim. Thresholds are pre-registered in
CLAUDE.md / THRESHOLD_CHANGES.md and were not adjusted post hoc.

## 2. The safety tail (F1)

Table: unsafe rate per small model x language, DIRECT mode, tail strata
(A-D, F). Which strata drive the failures? Which language is worst?

## 3. Routing headroom (F2) — repair matrix

Paste the repair matrix. Highlight: fraction fixed by RAG alone, by REASON,
only by ESCALATE, and fixed by nothing (= the ABSTAIN training signal for the
full build).

## 4. Energy

`unsafe_vs_joules.png` — the embryonic Pareto figure. Joules/query per
model x condition; note the DIRECT->RAG->REASON->ESCALATE cost gradient.

## 5. Rule-verifier precision

n rule-vs-human disagreements out of N manually checked outputs
(disagreement log attached). This estimate becomes Section 6.4 evidence in
the full paper.

## 6. Language effects (RQ3 early signal)

Non-English minus English unsafe-rate gaps; bonus-signal verdict (>= 10pp?).
Translation caveat: `translation_verified` status counts per language.

## 7. Limitations at pilot grade

- Retrieval corpus built from the same source docs (deliberately easy).
- Energy is GPU-only, single hardware target, batch size 1.
- Sample-size caveats: n per stratum x language is small; report exact counts.
- Any items dropped for unverifiable sources (list them).

## 8. Carry-forward decisions for the full build

Surviving item templates, verifier v1 spec changes, corpus fixes, expert-panel
asks (states, languages, tolerance bands to calibrate).
