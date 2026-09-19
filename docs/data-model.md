# Data model and working decisions

> **TL;DR:** Preserve source observations, link identities exactly, and store current conclusions separately. A later decision can change without deleting the earlier claim.

## Main layers

`snapshot` identifies an immutable acquisition. `source` describes where a claim came from. `person_observation` and `event_observation` retain source-specific records, including unparsed date text. `person_identifier` links canonical UUIDs to exact external or local identifiers, and observations record where each identifier appeared.

`assertion` holds a claim about a person, event or place. `relationship_assertion` holds a source relationship. `conclusion` is the current working view with a confidence label and rationale. Raw snapshot conclusions begin from tree-aggregate evidence and explicit review flags; they are not documentary proof. Research batches supply reviewed confidence directly.

`source_file` hashes local evidence bytes; file links and registered locations preserve provenance and placement boundaries. OCR/transcription fields track human-supplied status only. `research_question` collects targets, timelines, associates, hypotheses, searches and current reasoning. Renderers build reports from this store.

## Research input fields

The complete [editable example](../templates/research-batch.json) demonstrates every major section. Keep `format_version: 1`. `batch_id` must change when content changes. Person, source, assertion, relationship, search and hypothesis keys make references explicit.

| Section | Purpose and important fields |
|---|---|
| `people` | Stable `key`, display name, name confidence/rationale, `deceased: true`, optional exact `familysearch_id`, source reference |
| `sources` | Type, title, repository, collection, locator, URL/access date if known, evidence tier, citation and optional local-file metadata |
| `assertions` | Person/source keys, predicate, interpreted `value_text`, preserved `raw_value`, optional structured `parsed_value`, confidence and rationale |
| `relationships` | Parent/child/source keys, father/mother/null role, confidence and rationale |
| `question` | Title, status, summary, targets, anchors, timeline, associates, searches and hypotheses |

Evidence tiers: `original_record`, `derivative_record`, `authored_narrative`, `family_knowledge`, `tree_aggregate`. Working confidence: `accepted_working`, `plausible_lead`, `quarantined_contradiction`.

Search statuses: `planned`, `accessible`, `blocked`, `downloaded`, `processed`, `no_relevant_result`, `rejected`. Required actions: `none`, `sign_in`, `download`, `order`, `approve_payment`. These describe a plan; the toolkit performs none of these outside actions automatically.

Source-file rights: `public_domain`, `personal_research`, `restricted`, `private_family`. OCR status: `not_started`, `raw`, `corrected`, `not_applicable`. Transcription status: `not_started`, `partial`, `complete`, `not_applicable`. Rights fields do not grant permission or verify ownership.

## Exact identity and revisions

A research person's key becomes the store-wide `research_key` identifier `research:{key}`. It is stable across batches. Use a new key for a different person, even if their names match. A FamilySearch ID can connect an already known person exactly; conflicting exact identifiers reject the transaction. The software never checks provider IDs online.

RootsMagic RINs are local to one snapshot. Private-seed IDs and research keys are store-wide namespaces. The demo makes an explicit, fixture-specific crosswalk after identifying its invented RINs; it does not teach automatic name matching.

Documentary batches supersede the current parent claims for each explicit child-role slot they mention. Unspecified roles supersede the same parent-child pair only. Each new claim keeps its own confidence conclusion, so contrary evidence can coexist without row-order deciding a winner. Only accepted edges drive the working graph. Old raw claims persist. Personal-name assertions use the latest current conclusion for that predicate.

Raw relationship conflicts are retained with review codes. Cycles, competing explicit parent choices and conflicting accepted roles quarantine implicated working edges. A prior unresolved quarantine is carried into a later raw claim for the same pair or explicit slot. A curated revision can retire the previous current claims and state the reviewed choice.

## Dates and privacy

RootsMagic dates retain the original encoding and explicit parse status. Supported exact, qualified and interval dates keep year/month/day precision as supplied. A definitely reversed interval stays unparsed. Overlapping partial ranges are not rejected merely because their exact endpoints are unknown. Unsupported encodings remain visible for review.

Living flags influence privacy markers; they do not encrypt records, redact reports or authorize publication. Research batches require deceased people, but deceased-family information can still be sensitive. Coverage hides individual names in its metric rows while retaining acquisition labels and aggregate counts. Private folders and human review remain necessary.
