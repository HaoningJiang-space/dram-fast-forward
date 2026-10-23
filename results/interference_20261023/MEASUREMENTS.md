# Interference study measurements

Full captured FFN window: 224,896 requests; 211,456 accepted READ requests. Values below use three fresh-process CPU medians. These are host-simulator timings, not chip token/s.

| Profile | Mode | Loop CPU (s) | Loop speedup | Whole-process CPU (s) | Whole-process speedup |
|---|---|---:|---:|---:|---:|
| independent | reference | 1.001469 | 1.000x | 1.125162 | 1.000x |
| independent | event | 0.958440 | 1.045x | 1.080323 | 1.042x |
| independent | incremental | 0.690500 | 1.450x | 0.814152 | 1.382x |
| independent | bank_affine | 0.719517 | 1.392x | 0.841134 | 1.338x |
| independent | bank_rowhit | 0.708771 | 1.413x | 0.830796 | 1.354x |
| independent | bank_hybrid | 0.653507 | 1.532x | 0.775340 | 1.451x |
| shared | reference | 2.487353 | 1.000x | 2.597839 | 1.000x |
| shared | event | 2.470219 | 1.007x | 2.581037 | 1.007x |
| shared | incremental | 1.673256 | 1.487x | 1.783549 | 1.457x |
| shared | bank_affine | 2.192281 | 1.135x | 2.302403 | 1.128x |
| shared | bank_rowhit | 2.080832 | 1.195x | 2.192690 | 1.185x |
| shared | bank_hybrid | 1.625892 | 1.530x | 1.738100 | 1.495x |

| Profile | Symbolic plan | READ coverage in segments >=2 | Mean segment length >=2 |
|---|---|---:|---:|
| independent | bank_affine | 60.023% | 2.689 |
| independent | bank_rowhit | 61.195% | 3.389 |
| independent | bank_hybrid | 61.195% | 3.389 |
| shared | bank_affine | 33.836% | 2.834 |
| shared | bank_rowhit | 34.160% | 28.128 |
| shared | bank_hybrid | 34.160% | 28.128 |

Primary matrix: 66 cases, 198 exact plan/reference comparisons, 284,039 compared resource-exit states.

Cases: 9 smoke patterns + full window + 20 seeded stress cases + 3 targeted guard cases, each on both profiles. Each case compares affine/row-hit/hybrid plans with a fresh precise reference.
Four additional post-cleanup cases are separate relocation checks, not extra primary performance samples.
Negative result: on the independent-bank pressure trace, the hybrid prototype is about 0.55x reference and is much slower than incremental-only. It is not a universal default policy.
The old global-isolation mode is unsupported on the new shared-bus fixture and deliberately takes the ordinary reference path. Do not interpret its near-1x timing as a shared-bus opportunity estimate.
