"""In-sandbox embroidery conversion pipeline for design.embroidery.

Every module in this package is uploaded into the E2B embroidery sandbox for each
run (see ``backend/shared/providers/e2b_embroidery.py``) and executed there with
``python -m embroidery_sandbox.pipeline``. Nothing here runs in an API or worker
process: the worker never parses the untrusted SVG geometry itself.

Modules that only need the standard library (``limits``, ``svg_source``,
``ordering``, ``presets``, ``stitch_report``) are unit-tested in the backend test
suite. ``geometry``, ``bands``, ``border``, ``prepared_svg`` and ``preview`` need the template's pinned
packages (shapely, svgelements, Pillow) and are proven by real sandbox runs.
"""

UPLOADED_MODULES = (
    "__init__.py",
    "limits.py",
    "svg_source.py",
    "ordering.py",
    "presets.py",
    "bands.py",
    "geometry.py",
    "border.py",
    "prepared_svg.py",
    "stitch_report.py",
    "preview.py",
    "pipeline.py",
)
