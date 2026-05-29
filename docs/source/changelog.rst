Changelog
=========

Version 0.1.1
-------------

- Adopt sdypy package template conventions: flat layout, hatchling
  build, sphinx_book_theme docs on ReadTheDocs, manual changelog,
  version-sync release script.
- Add full Sphinx documentation with API reference at
  https://pygigevision.readthedocs.io.
- Add three vendor-neutral examples in ``examples/``: discover,
  bootstrap and XML download, grab one frame.
- Add ``CONTRIBUTING.rst`` and this changelog.
- Switch CI lint from flake8 to ruff (strict superset, includes
  formatter).
- Add Windows to the CI test matrix alongside Ubuntu (the protocol
  library's primary user platform).
- Polish: NumPy-style docstrings and complete type hints across the
  public surface.
- No public API changes; consumers of ``pyGigEVision 0.1.0`` continue
  to work unchanged.

Version 0.1.0
-------------

- Initial release. Pure-Python implementation of the GigE Vision
  protocol layer: GVCP control client, GVSP streaming receiver,
  GigE Vision standard register constants, GenICam XML download
  helper, optional ``bootstrap()`` convenience.
- 52 unit tests passing across Python 3.10–3.13 on Ubuntu and Windows.
- Tag-only private release; not published to PyPI.
