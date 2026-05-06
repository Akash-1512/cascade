"""cascade.scripts — operational scripts shipped with the package.

Each module here is invokable as ``python -m cascade.scripts.<name>`` and
exposes a small CLI. Scripts are idempotent where it makes sense — the seed
script in particular detects existing demo data and refreshes it rather than
creating duplicates.
"""
