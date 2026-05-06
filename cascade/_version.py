"""Single source of truth for the package version.

Read by ``pyproject.toml`` (via hatch dynamic metadata in future versions) and by the
running application for ``/health`` and structured-log enrichment.
"""

__version__ = "0.7.1"
