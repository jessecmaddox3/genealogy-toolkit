# Evidence-first Genealogy

![Follow the evidence. Make the story your own. A playful archive desk with a family tree, source cards and a magnifying glass.](docs/assets/genealogy-hero.png)

**Turn a family-history question into a research trail you can actually follow.** Keep original records, competing claims, your current conclusions and the next useful search together, on your own computer.

> **Start here:** [Explore the invented example](https://jessemaddox.com/projects/genealogy-toolkit/) or [download the ready-to-open demo](https://github.com/jessecmaddox3/genealogy-toolkit/releases/latest). No account, AI subscription or installation is needed to read the example. Running the research tools uses Python 3.12 or newer.

I built this for my own personal use: I wanted to keep the evidence and the uncertainty together while researching family history. This release includes the research engine and the way I organized the work, with entirely invented examples.

Make it your own, and feel free to improve mine. Hopefully it gives you a useful starting point, or at the very least some ideas. Cheers!

## What you get

An imported tree is a collection of claims. This toolkit keeps those claims available while giving you a separate working view of what you currently accept, what needs research and what conflicts.

- **A local evidence store.** Import supported RootsMagic `.rmtree` snapshots read-only, preserve observations and source hashes, and replay the same acquisition without duplicates.
- **Deliberate identity matching.** Exact identifiers can connect records across acquisitions. A shared name alone never merges people.
- **A research notebook with structure.** People, citations, documentary claims, relationships, source-file rights and processing status, timelines, associates, hypotheses, negative searches and next actions.
- **Five useful outputs.** A line audit, person dossier, hypothesis matrix, action queue and portable research-state JSON, plus an optional readable HTML view.
- **Honest coverage.** Separate people and parent-edge denominators, cohort definitions and unknown values. A count is not a proof score.
- **Reusable instructions.** [The research workflow](docs/research-guide.md), [editable inputs](templates/) and an [optional AI skill](skills/evidence-first-research/SKILL.md).

There are no runtime packages to download, no telemetry and no automatic archive requests. The software runs locally after Python is installed. The generated hero is illustration; the example records are conspicuously marked teaching text.

## New to GitHub? Start with the example

GitHub is the site holding the project files. You do not need a GitHub account or need to learn Git.

1. Open [the latest release](https://github.com/jessecmaddox3/genealogy-toolkit/releases/latest).
2. Under **Assets**, download `genealogy-toolkit-1.0.0-demo.zip`.
3. Extract the ZIP. On Windows, right-click it and choose **Extract All**. On a Mac, double-click it.
4. Open the extracted folder, then double-click **index.html**. It opens in your usual browser.
5. Choose **Read the research**. Everything in this example is invented. You can use it offline.

The demo archive contains readable reports and editable teaching examples. It is safe to explore without adding any of your own family information.

## Run the full demo on your computer

This creates a new local database and all the reports from scratch. It also demonstrates a living-person seed, a partial date, an unsupported raw date, a conflicting parent claim, exact identity links, repeat imports and a changed-hash rejection.

1. Install **Python 3.12 or newer** from [python.org](https://www.python.org/downloads/). Python is the program that runs these tools.
2. Download `genealogy-toolkit-1.0.0-source.zip` from the same release and extract it.
3. **Windows:** double-click `Start Demo.bat`. **Mac:** double-click `Start Demo.command`. It creates a fresh folder under `output/` and opens its report in your browser. [If it does not start, use the short troubleshooting steps.](docs/install.md)

The launcher needs no package installation and does not ask for any account or family records. It runs only the invented example. For your own research, follow [the step-by-step guide](docs/research-guide.md); working with your inputs currently involves editing JSON files and entering commands in a terminal.

### Comfortable with a terminal?

From the extracted source folder:

```sh
python3 start_demo.py --no-open
```

On Windows, use `py -3 start_demo.py --no-open`. To install the command in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-deps /path/to/evidence_first_genealogy-1.0.0-py3-none-any.whl
.venv/bin/genealogy demo --output output/my-first-demo
```

Download the wheel from the release. On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\genealogy.exe`. The wheel includes the SQL schemas and demo; it works outside the source folder. [Full installation guide](docs/install.md).

## How I designed it

```text
Immutable acquisition + hash
         ↓
Original observations and exact identity links
         ↓
Claims + source provenance + human review
         ↓
Current working conclusions
         ↓
Cohorts, coverage, research reports and next actions
```

The SQLite store separates observations from conclusions. Curated imports are transactional. An ancestry cycle or contradictory accepted parent choices reject the whole curated batch. Raw imports preserve conflicting claims and quarantine affected working relationships. Repeating a raw claim does not resolve an outstanding relationship conflict.

Documentary batches update the current claims for the explicit parent slots they mention. Include the alternatives you still want considered in that batch. Earlier raw assertions remain stored. Unspecified parent roles remain separate parent-child pairs. The [data model](docs/data-model.md) explains these semantics and the stable identity keys.

## Scope and limits

This is a **local Python research toolkit** with HTML and Markdown reports. It supports the RootsMagic schema checked by the reader; a changed application schema may need adaptation. Native citation-table extraction is not implemented, so documentary citations enter through research batches. There is currently no GEDCOM importer/exporter, DNA analysis, archive crawler, OCR engine, family-tree drawing interface or automatic genealogy research.

Confidence labels record working judgments. Imported tree claims can initially be `accepted_working` without documentary proof. A young-parent age flag is a review heuristic. Source rights and processing labels record your inputs; they do not verify rights or perform OCR. Cohort A contains ancestors and excludes the selected root; recompute cohorts after changing relationships.

**Your own inputs and reports are personal data.** Keep your research folder private. A filename guard, `.gitignore`, a `private` flag or an aggregate report is not an anonymizer. This public release contains no personal research or received family materials. See [privacy and boundaries](docs/privacy.md).

## Make it better

MIT licensed: use, adapt, redistribute and build on it, including commercially, while retaining the license notice. Suggestions, bug reports and pull requests are welcome. Useful contributions include new synthetic RootsMagic schema fixtures, clearer beginner workflows, additional source formats and tests for uncertain dates. [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Asset provenance](ASSETS.md).

The code and documentation were developed with AI assistance and reviewed with independent Astra passes. Running the toolkit does not call an AI model. The optional skill helps an assistant organize research; you control which files and services that assistant can access.
