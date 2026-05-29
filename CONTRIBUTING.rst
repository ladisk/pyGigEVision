Contributing to pyGigEVision
============================

Thanks for your interest in contributing! This guide describes the
development workflow.

Development setup
-----------------

1. Fork the repository on GitHub and clone your fork:

   .. code-block:: bash

      git clone https://github.com/<your-username>/pyGigEVision.git
      cd pyGigEVision

2. Install in editable mode with dev extras:

   .. code-block:: bash

      pip install -e ".[dev]"

   This pulls in pytest, sphinx, ruff, and the rest of the dev tools.

3. Create a feature branch off ``main``:

   .. code-block:: bash

      git checkout -b feature/my-change

Making a change
---------------

1. Make your code change.

2. Add or update tests in ``tests/``. Every behavioural change needs
   a test that would fail without the change.

3. Add or update docstrings on every public symbol you touched. Use
   NumPy-style format (Parameters / Returns / Raises / Examples).

4. Run the local checks:

   .. code-block:: bash

      pytest -v
      ruff check pyGigEVision tests
      ruff format --check pyGigEVision tests

   All three must pass.

5. Update ``docs/source/changelog.rst``: add a line under the next
   unreleased version block describing your change (or create the
   block if you're the first contributor since the last release).

6. If you touched the API, rebuild the docs locally and confirm the
   API page still renders cleanly:

   .. code-block:: bash

      sphinx-build -b html docs/source docs/build/html

7. Push to your fork and open a pull request against the ``main``
   branch of ``ladisk/pyGigEVision``.

Code style
----------

* Line length 100. ``ruff format`` enforces it.
* Modern type hints: ``str | None`` not ``Optional[str]``;
  ``list[dict]`` not ``List[Dict]``.
* ``from __future__ import annotations`` at the top of every module.
* f-strings, not ``.format()``.
* No bare ``except:``.

Documentation
-------------

The documentation is built with Sphinx and hosted on ReadTheDocs.

To build locally:

.. code-block:: bash

   pip install -r docs/requirements.txt
   sphinx-build -b html docs/source docs/build/html
   open docs/build/html/index.html

Setting up ReadTheDocs (one-time, maintainers only)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Sign in to https://readthedocs.org with the maintainer GitHub
   account.
2. "Import a Project" → select ``ladisk/pyGigEVision``.
3. Set the project slug to ``pygigevision``.
4. Trigger the first build manually from the RTD admin panel.

Releasing a new version (maintainers only)
------------------------------------------

1. Make sure ``main`` is green on CI.
2. Update ``docs/source/changelog.rst`` with the version's notes.
3. Tag the release commit:

   .. code-block:: bash

      git tag vX.Y.Z
      git push origin vX.Y.Z

4. The ``release-and-publish-to-pypi.yml`` workflow runs automatically
   on the tag push:

   * Syncs the version into ``pyproject.toml``, ``pyGigEVision/__init__.py``,
     and ``docs/source/conf.py`` via ``sync_version.py``.
   * Commits the sync back to ``main``.
   * Builds the sdist and wheel.
   * Publishes to PyPI using the ``PYPI_API_TOKEN`` repo secret.
   * Creates a GitHub Release with the built artifacts attached.

5. Verify the release on PyPI and the rebuilt docs on ReadTheDocs.

Reporting issues
----------------

Open an issue at https://github.com/ladisk/pyGigEVision/issues.
Include:

* Python version and OS.
* ``pyGigEVision.__version__``.
* The minimum code snippet that reproduces the problem.
* The full traceback if any.

License
-------

By contributing you agree that your contribution will be licensed under
the MIT License (see ``LICENSE``).
