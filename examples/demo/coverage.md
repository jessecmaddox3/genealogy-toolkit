# TL;DR

Cohort A has 3 eligible people across 12 coverage metrics, with 3 anomaly types flagged for review.

## Summary counts

- Eligible people: 3
- Coverage metrics: 12
- parent_edges: 1 metric, 2 eligible
- people: 11 metrics, 3 eligible
- Anomaly types: 3
- Evidence floor: `accepted_working`

## Snapshot acquisitions

These immutable RootsMagic source counts distinguish acquisitions and are not cohort denominators.

| Snapshot | People | Families | Child links | Events | Places |
|---|---:|---:|---:|---:|---:|
| synthetic-larkhaven-v1 | 8 | 3 | 3 | 10 | 1 |
## Coverage metrics

Each row states its own eligible, included, and unknown denominator for the selected cohort.

| Metric | Unit | Eligible | Included | Unknown | Cohort | Evidence floor |
|---|---|---:|---:|---:|---|---|
| accepted_parent_edges | parent_edges | 2 | 2 | 0 | A | accepted_working |
| birth_date | people | 3 | 3 | 0 | A | accepted_working |
| citations | people | 3 | 1 | 2 | A | accepted_working |
| death_date | people | 3 | 0 | 3 | A | accepted_working |
| familysearch_id | people | 3 | 0 | 3 | A | accepted_working |
| known_child_sets | people | 3 | 3 | 0 | A | accepted_working |
| notes | people | 3 | 0 | 3 | A | accepted_working |
| people | people | 3 | 3 | 0 | A | accepted_working |
| primary_names | people | 3 | 3 | 0 | A | accepted_working |
| raw_places | people | 3 | 3 | 0 | A | accepted_working |
| recorded_lifespan | people | 3 | 0 | 3 | A | accepted_working |
| resolved_coordinates | people | 3 | 0 | 3 | A | accepted_working |

## Anomalies

Anomalies remain visible for review and are not promoted to accepted evidence.

- duplicate_external_id: 0
- quarantined_relationship_edge: 0
- unparsed_date: 0
