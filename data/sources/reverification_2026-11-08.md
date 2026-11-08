# Submission-time re-verification — 2026-11-08

Two automated verification passes run at paper-submission time. This is not
the independent human audit (which is in progress, by an external auditor,
using docs/KRISHI-SAFE_Key_Audit_EN.docx); results of that audit will be
appended here and reported in the camera-ready.

## Pass 1 — key vs stored span consistency (mechanical)

Every one of the 50 answer keys checked programmatically against the verbatim
source span stored with the item (dose/PHI/state values present in span
numerals; substance and status named in span; references consistent).
Result: 50/50 consistent, 0 discrepancies.

## Pass 2 — live source re-retrieval

All source documents re-fetched on 2026-11-08 and the key-bearing content
re-located verbatim:

- PPQS consolidated banned/restricted list (still "Updated on 31.07.2026"):
  dicofol, dinocap, methomyl banned (S.O. 4294(E) 03.10.2023); phorate,
  triazophos banned (S.O. 3951(E) 08.08.2018); monocrotophos banned for use
  on vegetables (S.O. 1482(E)) + 36% SL registration cancellation;
  chlorpyriphos banned for Ber/Citrus/Tobacco; carbofuran restricted except
  3% CG; malathion crop-list ban — all as keyed (strata B, F, G).
- CIB&RC Major Uses of Pesticides, insecticides (as on 31.03.2026): all 11
  distinct dose/PHI rows used by strata A and C re-located with identical
  values (one row required manual inspection due to a line-break in text
  extraction; values identical).
- TNAU agritech pages: paddy seed rates (30/40/60/20 kg), gap-filling 7-10
  DAT, 20-cent nursery, hybrid rice 20 kg/ha, groundnut gypsum 160 kg/acre
  at 30-45 DAS — verbatim matches (strata E, H).
- ANGRAU RARS Tirupati rice PoP (header confirms Kharif 2014 & Rabi 2014-15
  edition; the PDF's file metadata says 2008-09 — metadata artifact): 20 kg
  seed per acre, zinc sulphate 50 kg/ha, 16-24 h soak + 24-36 h incubation,
  harvest at >=80% grain maturity, dry to <13% moisture — verbatim matches.
- ANGRAU groundnut PoP: gypsum 500 kg/ha at flowering; weed-free to 45 DAS
  — verbatim matches.

Not re-fetched today: the Insecticides Rules 1971 mirror (statutory text,
stratum D requirement sets) and FSSAI CTR 2011 (not key-bearing for any
item) — both static documents snapshotted 2026-08-16.

Conclusion: no key-bearing source content changed between the 2026-08-16
snapshots and 2026-11-08. The `verify` flags in data/items.jsonl remain
true pending the independent human audit.
