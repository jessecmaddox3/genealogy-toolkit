# Contributing

> **TL;DR:** Improvements are welcome. Use invented data and keep the useful behavior intact.

This was built for personal use and shared as a starting point. Small fixes, clearer instructions and thoughtful extensions are all useful. Open an issue describing the observable problem or send a pull request with a focused change.

Install Python 3.12+, then `python -m pip install -r requirements-dev.txt` and `python -m pytest -q` from this folder. Tests use invented records and block network access. Add a regression for a behavioral fix. Do not connect a real account or include a personal database in a test.

Before proposing a new import format, include a minimal independently created schema fixture and describe unsupported fields. Preserve raw values and provenance; do not silently drop uncertain dates or merge people by name. Keep dependency-free offline use available.

Do not post family records, private URLs, provider exports, credentials or received materials in an issue. Share a minimal invented reproduction instead. Contributions are provided under the project's MIT license.
