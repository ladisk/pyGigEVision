API reference
=============

Top-level
---------

.. automodule:: pyGigEVision
   :no-index:
   :no-members:

The top-level package re-exports the most commonly used symbols from
the submodules below for convenience. See the per-module sections for
full documentation:

* :class:`~pyGigEVision.gvcp.GVCPClient`, :exc:`~pyGigEVision.gvcp.GVCPError` (from :mod:`pyGigEVision.gvcp`)
* :class:`~pyGigEVision.gvsp.GVSPReceiver` (from :mod:`pyGigEVision.gvsp`)
* :func:`~pyGigEVision.genicam.fetch_genicam_xml`, :func:`~pyGigEVision.genicam.parse_first_url` (from :mod:`pyGigEVision.genicam`)
* :func:`~pyGigEVision.bootstrap.bootstrap` (from :mod:`pyGigEVision.bootstrap`)

``pyGigEVision.discover`` and ``pyGigEVision.force_ip`` are top-level aliases for
:meth:`~pyGigEVision.gvcp.GVCPClient.discover` and
:meth:`~pyGigEVision.gvcp.GVCPClient.force_ip` respectively.
``pyGigEVision.standard`` is the public submodule of GigE Vision register constants.

Control protocol (GVCP)
-----------------------

.. automodule:: pyGigEVision.gvcp
   :members:
   :show-inheritance:

Streaming protocol (GVSP)
-------------------------

.. automodule:: pyGigEVision.gvsp
   :members:
   :show-inheritance:

GenICam descriptor download
---------------------------

.. automodule:: pyGigEVision.genicam
   :members:
   :show-inheritance:

Bootstrap helper
----------------

.. automodule:: pyGigEVision.bootstrap
   :members:
   :show-inheritance:

GigE Vision standard registers
------------------------------

.. automodule:: pyGigEVision.standard
   :members:
