# pyGigEVision for agents

pyGigEVision is a pure-Python implementation of the GigE Vision protocol (GVCP
control + GVSP streaming). No vendor SDK, no GenTL producers. It is the
protocol layer that vendor-specific GigE Vision camera drivers build on top of.

This file is for coding agents. For the full human guide see
[CONTRIBUTING.rst](CONTRIBUTING.rst); the commands here mirror it.

## Documentation

Published at https://pygigevision.readthedocs.io/en/latest/

Start at https://pygigevision.readthedocs.io/en/latest/llms.txt for the page
index, or fetch https://pygigevision.readthedocs.io/en/latest/llms-full.txt for
the whole corpus in one request. Every page is also available as Markdown by
replacing the `.html` extension with `.md`.

| Doing | Read |
|---|---|
| First contact: discover, bootstrap, grab a frame | getting_started.md |
| How GVCP / GVSP / GenICam fit together | protocol.md |
| Full API surface | api.md |
| Runnable scripts | examples.md |

Public API (all re-exported at the top level): `GVCPClient`, `GVCPError`
(gvcp); `GVSPReceiver` (gvsp); `fetch_genicam_xml`, `parse_first_url`
(genicam); `bootstrap` (bootstrap); `discover` (alias for
`GVCPClient.discover`); register constants in `pyGigEVision.standard`.

## Setup

```bash
pip install -e ".[dev]"
```

Pure-Python protocol code (depends on numpy and psutil), so there are no SSH keys or
private dependencies to configure.

## Test, lint, format

```bash
pytest -v
ruff check pyGigEVision tests
ruff format --check pyGigEVision tests
```

There are no hardware tests: the protocol is vendor-agnostic and hardware
coverage lives in the vendor drivers that depend on this package.

## Conventions

- Line length 100, enforced by `ruff format` (double quotes).
- `from __future__ import annotations` at the top of each module; modern type
  hints (`str | None`, `list[dict]`).
- f-strings, not `.format()`. No bare `except:`.
- NumPy-style docstrings (Parameters / Returns / Raises / Examples) on every
  public symbol.
- No em dashes in user-facing docs, docstrings, or changelogs.
- Add a line to `docs/source/changelog.rst` under the next version for any
  user-visible change.
- Branch off `main`; open pull requests against `main`.

## Project layout

```
pyGigEVision/    protocol package: gvcp.py, gvsp.py, genicam.py, bootstrap.py, standard.py
tests/           pytest suite (protocol parsing, no hardware)
examples/        runnable scripts (01_discover.py, 02_bootstrap_and_xml.py, 03_grab_one_frame.py)
docs/source/     Sphinx docs (RST source)
```

Requires Python 3.10 or newer.
