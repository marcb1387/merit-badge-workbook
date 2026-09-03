# merit-badge-workbook

Generates a printable requirements checklist or note-taking workbook for any
Scouting America merit badge, pulling the requirements from the official
source: <https://www.scouting.org/skills/merit-badges/all/>

Output formats: Markdown, printable HTML, PDF, and JSON.

## Install

macOS / Linux:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[pdf]"
```

Windows (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e ".[pdf]"
```

If PowerShell refuses to run the activate script, either allow it for the
current shell with `Set-ExecutionPolicy -Scope Process RemoteSigned`, or skip
the venv entirely and use `py -m pip install --user -e ".[pdf]"`.

That puts `mbworkbook` and `mbworkbook-gui` on your PATH. Pip will warn if the
Scripts directory (usually `%APPDATA%\Python\Python3xx\Scripts`) is not on
PATH; you can ignore that and use `py -m mbworkbook` instead.

Or run it straight from the source tree without installing:

```bash
pip install requests beautifulsoup4 lxml reportlab
python -m mbworkbook --help
```

## Use

### Desktop window

```bash
mbworkbook-gui          # or:  python -m mbworkbook --gui
```

![Options tab](docs/screenshot-options.png)

Pick badges on the left (Ctrl-click or Shift-click for several at once), set
the options on the right, hit Generate. The Preview tab shows the parsed
requirement tree so you can check a badge came out right before printing a
stack of them; the Log tab records what was written and what failed.

![Preview tab](docs/screenshot-preview.png)

Fetching happens on a background thread, so the window stays responsive and a
batch of thirty badges can be left to run. Your format, style, counselor, unit
and output folder are remembered between sessions in
`~/.config/merit-badge-workbook/gui.json`.

Tkinter ships with Python on Windows and macOS. On Debian or Ubuntu it is a
separate package:

```bash
sudo apt install python3-tk
```

### Command line

```bash
# What badges exist? (* marks Eagle-required)
mbworkbook --list
mbworkbook --list --eagle-only

# A checklist in Markdown (default)
mbworkbook Camping

# A printable PDF workbook with writing space, pre-filled
mbworkbook "personal management" -f pdf --style workbook \
    --scout "A. Scout" --counselor "M. Counselor" --unit "Troop 379"

# Pick from a menu
mbworkbook --pick -f html

# Structured data for something else to consume
mbworkbook Cooking -f json -o cooking.json

# Every Eagle-required badge into one folder
mbworkbook --all --eagle-only -f pdf -o ./eagle-packets/
```

Both front ends run through the same `service.py`, so anything the window can
do the CLI can do too — handy if you want this in a cron job or a Makefile.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--style workbook` | Adds ruled writing space under each leaf requirement |
| `--note-lines N` | How many ruled lines (default 4) |
| `--no-signoff` | Drops the date / counselor-initials columns |
| `--no-resources` | Drops the "Resources:" links some badge pages carry |
| `--refresh` | Bypass the cache and re-fetch |
| `--dump-html page.html` | Save the raw page, for when parsing goes wrong |
| `--html-file page.html` | Parse a saved page instead of fetching |

Pages are cached for a week under `~/.cache/merit-badge-workbook/`
(override with `MBW_CACHE_DIR`). Requests are rate-limited to one per second
and identify themselves; set `MBW_CONTACT` to put your email in the User-Agent.

## How the parsing works

The badge pages are Elementor-generated and the markup is not consistent
between badges. Sub-requirements show up three different ways depending on the
page: inside accordion panels, inside nested `<ol>` lists, or as one text block
split by `<br>`.

Pages on the current template wrap each requirement in `.mb-requirement-item`
and put the printed marker in its own `<span>`, separate from the text. The
parser reads that structure directly when it is present (`parser.structured_lines`),
since it says the hierarchy unambiguously.

For anything else, it falls back to a layout-independent pass that:

1. Finds the region around the heading containing "Requirements".
2. Flattens it into text lines in document order (`parser.extract_lines`).
3. Rebuilds the hierarchy from the printed markers — `1.`, `a.`, `(1)`, `ii.` —
   using a stack of marker *types* (`parser.build_tree`). A type already on the
   stack means "sibling at that level"; a new type means "one level deeper".
   That handles any numbering scheme a badge happens to use.

Along the way it drops page furniture (nav, "the requirements will be fed
dynamically…", "View Related Merit Badges"), and it will not start collecting
until it sees requirement `1.`, so Scout Life article text on the same page
that mentions "requirement 4" does not leak in.

Lines with no marker attach to the previous requirement as a continuation, and
lines starting with `Resources:` become notes rather than requirements.

## Known caveats

- Eyeball the output for an unfamiliar badge before you hand a stack of these
  to Scouts. If one comes out wrong, grab the page with `--dump-html`. For a
  page on the current template the fix is usually in `structured_lines`; for an
  older-looking page it is usually a new pattern in `NOISE_LINE` or
  `TITLE_CLASS_HINTS` in `parser.py`.
- Some badge pages say requirements are "fed dynamically using the Scoutbook
  integration". That text is boilerplate and is dropped — the requirements
  themselves are in the served HTML. But if a badge ever does parse to zero
  requirements, that is the case to suspect: fetch the page once in a browser,
  save it, and pass it with `--html-file`.
- Requirements change. Re-run with `--refresh` before each new class rather
  than reusing last year's PDFs, and check the retrieval date printed on every
  sheet.
- The requirement text belongs to Scouting America. These sheets are a
  note-taking aid for Scouts and counselors; the official requirements are the
  ones on scouting.org and in the current pamphlet. Don't redistribute the
  generated files as if they were official workbooks.

## Tests

```bash
pip install pytest
python -m pytest tests -q
```

The fixture in `tests/fixtures/sample_badge.html` reproduces all three markup
shapes seen on real pages, with invented requirement text. The GUI tests cover
the background-job plumbing and the service layer; the window itself needs a
display and is not exercised in CI.

## Layout

```
pyproject.toml     Packaging; defines the mbworkbook / mbworkbook-gui commands
mbworkbook/
  __init__.py      Package marker and version
  __main__.py      Entry point for `python -m mbworkbook`
  models.py        Badge / Requirement dataclasses, tree walking
  fetch.py         HTTP with disk cache and rate limiting
  catalog.py       A-Z index scraping, fuzzy badge-name resolution
  parser.py        HTML -> requirement tree
  render/
    __init__.py    Markdown + JSON, shared WorkbookOptions
    html.py        Printable HTML with a print stylesheet
    pdf.py         ReportLab PDF
  service.py       fetch -> parse -> render, shared by both front ends
  cli.py           Argument handling
  gui.py           Tkinter window (stdlib only)
tests/
  test_parser.py   Markers, tree building, page parse, catalog, renderers
  test_gui.py      Background-job plumbing and the service layer
  fixtures/        Synthetic badge page covering the legacy markup shapes
docs/              Screenshots and a sample generated workbook
```

Everything under `mbworkbook/` uses relative imports, so the files have to stay
in that package directory — flattening them into one folder breaks every
`from .models import ...`.
