Changelog
=========

Version 0.2.0
-------------

- ``GVCPClient.discover()`` now sweeps every host network interface (via
  psutil), sending global and per-subnet broadcasts, so cameras on secondary
  NICs and USB-to-GigE adapters are found by default.
- Discovery results now include the camera ``mac``.
- Added ``GVCPClient.force_ip()`` to assign an IP to a camera by MAC
  (GVCP FORCEIP), for re-homing wrong-subnet cameras.
- ``psutil`` is now a required dependency.
- Discovery results now include ``interface_ip``, the host interface the
  camera replied on, so vendor drivers can bind the correct local interface
  when connecting.
- Added ``GVSPReceiver.reset_resend_stats()`` to clear per-stream resend
  counters between downloads.
- ``force_ip()`` is now available as a top-level ``pyGigEVision.force_ip``
  and sweeps all network interfaces by default; accepts an optional
  ``interface_ip`` argument to restrict the sweep to one interface.
- ``pyGigEVision.standard`` is now documented as a public submodule.
- GenICam XML download now accepts bare-hex ``FIRST_URL`` fields emitted by
  some cameras (previously raised an error); READMEM reads are 4-byte aligned
  per the GigE Vision spec.
- GVSP frames returned by the receiver are now always writable (previously
  some assembled frames were read-only).
- Frame metadata now includes a ``complete`` flag indicating whether all
  expected packets arrived for that frame.
- Added a ``py.typed`` marker (PEP 561) so downstream type checkers consume
  the inline type annotations directly.
- CI now gates the PyPI publish workflow on tests passing and adds a
  Sphinx ``-W`` docs-build check.

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
