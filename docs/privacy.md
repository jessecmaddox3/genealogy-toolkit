# Privacy and source boundaries

> **TL;DR:** The release uses wholly invented examples. Your research inputs, SQLite store, report outputs, file paths and screenshots can contain personal information and should stay private.

## What this release contains

The public source was extracted into a fresh repository from owned software. Personal databases, records, downloaded sources, family materials, DNA files, photographs, reports, agent memories, credentials and old Git history are excluded. Personal test cases were replaced with independently invented scenarios and counts. The public demo's names, places, dates, relationships, sources and chronology were authored together, not anonymized by swapping names.

Some interoperability unit tests use invented provider-shaped strings such as `TEST-001`. They are test fixtures, not officially reserved identifiers, and are never looked up. The public demo has no FamilySearch identifiers. No provider material or third-party family project is included.

## What the software does

The runtime makes no network requests. It reads the files you name and writes local databases and reports. It keeps raw observations and source provenance. Non-public source-file labels require placement under `data/private/`, and report output checks avoid overwriting registered source files, research inputs or the database.

These are narrow protections, not anonymization or access control. Reports can contain names, notes, citations, URLs, paths and family relationships. Aggregate coverage includes acquisition labels and counts. A private flag does not remove these from every output, and an ignored file can still be shared manually. Use a private working folder outside the public source checkout.

## Before sharing your own adaptation

Review the exact files and archives, including tests, example screenshots, generated reports, metadata and Git history. Use invented examples. Keep received materials private unless their owner has clearly authorized redistribution. Remove credentials and personal defaults from configuration. A secret scan is useful but cannot determine whether a story or relationship identifies a family.

Do not attach personal records to public issues. Report a privacy/security concern through the route in [SECURITY.md](../SECURITY.md). If you use an AI assistant, its data handling is separate from this local toolkit; provide only what you intend that service to receive.
