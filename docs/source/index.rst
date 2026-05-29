pyGigEVision
============

Pure-Python implementation of the GigE Vision protocol (GVCP + GVSP).
``pyGigEVision`` is the foundation other vendor-specific GigE Vision
camera drivers can build on top of. It exposes the protocol primitives
— discovery, control register access, streaming reception, and GenICam
descriptor download — without bundling any vendor-specific behaviour.

The package is pure Python: no compiled extensions, no vendor SDKs,
no GenTL producers.

Quickstart
----------

.. code-block:: python

    from pyGigEVision import discover, bootstrap, GVSPReceiver

    cameras = discover()
    if cameras:
        ip = cameras[0]["ip"]
        client, xml = bootstrap(ip)
        # ... configure registers, start GVSPReceiver, grab frames

See :doc:`getting_started` for a step-by-step introduction.

Contents
--------

.. toctree::
   :maxdepth: 2

   getting_started
   protocol
   api
   examples
   changelog

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
