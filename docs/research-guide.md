# From a question to a research trail

> **TL;DR:** Run the invented demo first. Keep your own work in a separate private folder, state one question, record sources and competing claims, then generate the same reports. A working conclusion stays revisable.

## 1. See the whole loop

Run `genealogy demo --output output/first-demo`. It creates a new folder, a synthetic RootsMagic database, a manifest, a separate canonical SQLite store, an example private seed, source text, a documentary batch, cohorts, coverage and all five research reports. Open its `index.html`.

The example has two invented people called Ari Fable. The 1847 register's stated age fits the older person. A later index confuses them. An implausible parent-age claim is retained and quarantined, a different hypothesis is rejected, and a missing index entry is recorded without claiming that absence proves anything. Read the source text and the next action, not just the status labels.

Local UUIDs and timestamps are new on each run; the teaching inputs and semantic results are fixed. `demo-verification.json` records repeat-import and changed-hash checks. `data/private/` in this generated demo contains invented text only.

## 2. Start your own private research folder

Create a folder outside this source repository, for example **My private genealogy** in Documents. Back it up in a location appropriate for your family's information. Copy `templates/research-batch.json` and `templates/private-seed.json` there. Those are editable invented examples, not automatic research.

A JSON file is plain text with named fields, lists and quoted strings. Edit a copy with a plain-text editor. Retain commas, quotes and brackets. The loader rejects unknown fields, unsupported status values and missing references with a short error. [The data model](data-model.md) explains the fields.

Start with one question. Replace the example people, narrative, sources, dates and relationships together. Set `familysearch_id` to `null` unless you have verified the exact identity. Do not reuse another person's `key`. Keep real living people in a private seed; documentary research batches require `deceased: true`.

After installation, open a terminal in your private folder. These commands are the same on Mac and Windows when `genealogy` is on your path; otherwise use the full `.venv/bin/genealogy` or `.venv\Scripts\genealogy.exe` path from the install guide.

```sh
genealogy init-store --database research.sqlite
genealogy ingest-research --database research.sqlite --root . research-batch.json
```

The included template retains the invented question. To try it unchanged, create a folder named `reports`, then run:

```sh
genealogy research-report --database research.sqlite --question-title "Which Ari Fable appears in the Larkhaven workshop register?" --output-dir reports --html
```

Open `reports/index.html`. After editing the question, put its exact title in the command. Real reports contain your inputs; keep them private. Re-running a report replaces its output files after checking for collisions with registered sources, batches and the database.

## 3. Record evidence before deciding

For each source, record what it is, where it came from, its locator and citation, and what it actually says. Preserve the raw wording separately from your interpretation. A copy, an index, a later narrative and an original record deserve different descriptions.

For a local file, record a path below your research root. A source with `personal_research`, `restricted` or `private_family` rights must live under `data/private/`. `public_domain` is an assertion you supply, not a finding by the software. Files are hashed and registered without being copied or uploaded. There is no automatic OCR or archive download.

`accepted_working` means you currently use the claim. `plausible_lead` keeps an idea available without using it as an accepted lineage edge. `quarantined_contradiction` records a conflict. Give each judgment a reason. Keep contrary evidence, rejected hypotheses and negative searches with the question.

## 4. Revise deliberately

A `batch_id` identifies immutable content. Replaying the same content is safe; changing it under the same ID is rejected. For a substantive revision, create a new batch ID, such as `workshop-question-v2`. Keep the same person keys only for the same people, and the same question title when updating that question.

For each explicit child + father/mother slot mentioned in a new documentary batch, that batch replaces the prior current claims for that slot. **Include every alternative you still want in the current view.** It may contain accepted and nonaccepted claims together. Different accepted parents for one explicit slot, conflicting accepted roles, self-parent links and ancestry cycles reject the whole curated batch. Old assertions remain in the store.

Unspecified parent roles use parent-child pairs and can coexist. Repeating a conflicted raw tree claim does not clear its outstanding review. A curated research update must state the revised decision. Names alone never merge people; exact identity links require a separately justified match. The demo's hardcoded crosswalk is solely for its invented fixture.

## 5. Import a RootsMagic acquisition

Work with a closed, stable **copy** of a supported `.rmtree` file. Keep it separate from the canonical database. A live SQLite file can have companion journal files; obtain a consistent copy before importing.

```sh
genealogy manifest --root . --output acquisition-manifest.json acquisition.rmtree
```

Open the manifest in a text editor. Copy the **`sha256` value for `acquisition.rmtree`**, a 64-character string. Then run:

```sh
genealogy ingest-rm --database research.sqlite --snapshot-id acquisition-v1 --manifest-hash REPLACE_WITH_THE_FILE_SHA256 acquisition.rmtree
```

Despite its historical option name, `--manifest-hash` takes the input file's hash, not the hash of the manifest JSON. The CLI verifies the source hash before and after extraction. The importer is read-only and rejects unsupported schema/data rather than silently dropping rows. This reader preserves snapshot-record provenance; native RootsMagic citation-table extraction is not implemented.

Same FamilySearch IDs can connect deceased records across acquisitions. Local RootsMagic record numbers are scoped to one snapshot, so reusing the same number in another file does not imply identity. No online lookup happens.

## 6. Recompute cohorts and coverage

Choose a canonical `person_id` in your SQLite store, or use the demo's root from `cohorts.json`. Recompute after relationship changes:

```sh
genealogy cohorts --database research.sqlite --root-person-id REPLACE_WITH_CANONICAL_UUID
genealogy coverage --database research.sqlite --cohort A --markdown reports/coverage.md --json reports/coverage.json
```

The cohorts scope different research questions; they can overlap. A is accepted ancestors excluding the root. B is children of qualifying ancestral family units with at least two accepted parents. C is spouses of those children outside A/B. D is deliberately curated associates with a reason. Z is remaining background people. A partial one-parent family does not automatically qualify as a complete sibling group.

Coverage measures what is recorded at the `accepted_working` evidence floor. It separates people from parent edges and preserves unknowns. Source-acquisition totals are not cohort denominators. Aggregate output still includes snapshot labels and counts, so review it before sharing.

## Optional AI assistance

Give an assistant the [research skill](../skills/evidence-first-research/SKILL.md) and only the files you intend it to access. Start with invented data. Your assistant may use a cloud service even though this toolkit itself is local. The skill requires source attribution, uncertainty, distinct identities and explicit control over outside actions. You remain responsible for the research and publication decisions.
