# Install and start

> **TL;DR:** Reading the demo needs only a browser. Running the engine needs Python 3.12 or newer. The source launcher needs no pip install, account, archive access or AI subscription.

## Start without installing anything

Download the release's `demo.zip`, extract the folder and open `index.html`. Keep the folder together: the research reader links to its sibling reports. Opening the ZIP's preview without extracting it can break those links.

## Run the source launcher

Install Python from [python.org](https://www.python.org/downloads/). Extract the **source ZIP**. On Mac, double-click `Start Demo.command`; on Windows, double-click `Start Demo.bat`. A terminal window runs the program, then a browser opens the local report. Every run uses a new folder. Nothing is uploaded.

If macOS does not run the command file, use Terminal: type `python3 ` with a trailing space, drag `start_demo.py` from the extracted folder into Terminal, and press Return. If that Python is too old, install a current Python from python.org. You do not need to disable operating-system protections.

On Windows, open Terminal in the extracted folder and run `py -3 start_demo.py`. If `py` is unavailable, try `python start_demo.py`. The launcher prints the report's full path if your browser does not open. Double-click that file manually.

If you get a permission error, move the extracted folder to a location you own, such as Documents, then run again. Existing demo folders are never overwritten. The Python command itself can be checked with `python3 --version` or `py -3 --version`.

## Install the command-line tool

Download `evidence_first_genealogy-1.0.0-py3-none-any.whl` from the release. A wheel is Python's installable package. Create a virtual environment, which is a folder containing an isolated installation.

**Mac or Linux:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-deps /full/path/to/evidence_first_genealogy-1.0.0-py3-none-any.whl
.venv/bin/genealogy demo --output output/first-demo
```

**Windows, PowerShell:**

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --no-deps C:\full\path\to\evidence_first_genealogy-1.0.0-py3-none-any.whl
.venv\Scripts\genealogy.exe demo --output output\first-demo
```

Replace the wheel path with the downloaded file's actual location. Quotes are needed around a path containing spaces. `--no-deps` avoids dependency downloads. This package has no runtime dependencies.

For development, install `requirements-dev.txt`, then `python -m pip install -e .`. That setup can download build and test tools. Run `python -m pytest -q` from this project folder. Source-only invocation is also available with `PYTHONPATH=src python3 -m genealogy --help` on Mac/Linux.

## Remove or update

Delete the isolated `.venv` folder to remove the installed tool. Your research data is separate. Back up your research folder before changing versions; this release makes no promise of automatic migration from unrelated private development databases. Install a new release into a new environment and test a copy of your research first.
