# PearScarf Evaluation Metrics
**pearscarf-eval · Metrics Reference**

---

## Overview

PearScarf performs three sequential operations on every ingested record: relevance filtering, structured extraction, and graph integration. Each operation introduces distinct failure modes. The metrics defined here are scoped to these failure modes — derived from the specific correctness criteria of a temporal knowledge graph system, not adapted from general NLP benchmarks.

Metrics are computed against a ground truth dataset of synthetic records with fully annotated expected outputs. All metrics are defined over a fixed evaluation window `(dataset_version, pearscarf_version)` to enable reproducible comparison.

---

## Definitions

**Record** — a single ingested unit (email, calendar event, Slack message, etc.)

**Fact-edge** — a labeled, attributed edge in the graph; the atomic unit of extracted knowledge. Carries: `fact`, `category`, `confidence`, `source_record`, `valid_at`, `invalid_at`.

**E** — the set of fact-edges annotated as ground truth for a given record or dataset.

**X** — the set of fact-edges produced by PearScarf for the same input.

**Noise record** — a record annotated as containing no extractable facts.

**Resolution pair** — a pair of entity references annotated with an expected resolution outcome: `merge` or `split`.

---

## Core Metrics

### 1. Extraction Recall

> Did PearScarf find everything that should have been found?

`correct_extractions / total_expected_facts`

Missing facts do not surface as errors at runtime — they manifest as incomplete answers at query time. Recall failures are silent.

**Primary failure mode:** under-extraction; aggressive noise filtering applied to signal-bearing records.

---

### 2. Extraction Precision

> Did PearScarf extract only things that are actually true?

`correct_extractions / total_extracted_facts`

Precision failures corrupt the graph with facts that were never true.

**Primary failure mode:** hallucinated entities, incorrect category assignment, spurious relationship inference.

---

### 3. Graph Fidelity (F1)

> How close is the resulting graph to the expected graph?

`2 · precision · recall / (precision + recall)`

The **primary scalar metric** for version-over-version comparison and release regression. Penalizes imbalance — a system that extracts everything scores high recall but low precision; F1 forces both to be high simultaneously.

---

### 4. Noise Rejection Rate

> Did PearScarf correctly ignore records that have nothing to extract?

`noise_records_with_zero_writes / total_noise_records`

Curation — knowing what *not* to write — is as critical as extraction quality. A system that writes indiscriminately produces a graph that grows without becoming more useful.

**Primary failure mode:** phantom entity creation; spurious edges from irrelevant content.

---

### 5. Entity Resolution Accuracy

> Did PearScarf correctly collapse alias references to a single canonical node?

`correct_resolution_decisions / total_resolution_pairs`

Entity fragmentation is a compounding failure: a person split into two nodes causes half their associated facts to become unreachable under either identifier. Evaluated over annotated resolution pairs, each labeled `merge` (same entity, different surface forms) or `split` (different entities, similar surface forms).

**Primary failure mode (merge):** fragmentation of the same real-world entity across multiple nodes.
**Primary failure mode (split):** conflation of distinct entities into a single node.

---

### 6. Temporal Accuracy

> Did facts land at the correct point in time?

`facts_with_correct_valid_at / total_facts_with_temporal_annotation`

Measures whether `valid_at` reflects when a fact became true in the world, not when the record was ingested. For superseded facts, also checks that `invalid_at` is correctly set on the predecessor edge.

**Primary failure mode:** substituting ingestion time for event time; failure to invalidate superseded facts when a deadline or status changes.

---

## Metric Tiers

| Tier | Metric | Role |
|---|---|---|
| **Primary** | Graph Fidelity (F1) | Version comparison, release regression gate |
| **Diagnostic** | Extraction Recall, Extraction Precision, Noise Rejection Rate | Root cause analysis on F1 regressions |
| **Specialized** | Entity Resolution Accuracy, Temporal Accuracy | Targeted regression on structurally hard cases |

Primary metrics are computed on every evaluation run. Specialized metrics require richer ground truth annotation and are evaluated per dataset milestone.

---

## Ground Truth Schema

Each record in an evaluation dataset carries the following annotation fields:

```
expected_entities       list of expected nodes (type, canonical name, known aliases)
expected_facts          list of expected fact-edges (entity refs, category, fact text, valid_at)
is_noise                boolean — true if the record should produce zero graph writes
resolution_pairs        list of (ref_a, ref_b, expected: merge | split)
temporal_assertions     list of (fact ref, expected valid_at, expected invalid_at if applicable)
```

A fact-edge match between `X` and `E` requires agreement on: entity references, category, and fact semantics. Exact string match is used by default; semantic match is logged separately.

---

## Versioning

Every evaluation run is identified by the tuple `(dataset_version, pearscarf_version)`. Metrics are meaningful as deltas, not absolutes.

```
ΔF1 = F1(dataset_v, pearscarf_vN) − F1(dataset_v, pearscarf_vN-1)
```

Dataset version is held fixed when measuring system changes. PearScarf version is held fixed when measuring dataset difficulty changes.