"""Reference workflow fixtures for the agent simulation lab.

Each module in this package is a self-contained, deterministic, offline
fixture for one realistic 2026 agentic workflow:

- ``returns_resolution``: e-commerce returns and refunds resolution agent.
- ``onboarding``: HR onboarding coordinator agent.
- ``disputes``: banking dispute resolution agent.

Design documents for the workflows live in ``docs/reference_workflows/``.
Additional reference workflows contributed by other builders may live in
per-workflow subpackages, each with its own ``DESIGN.md`` and ``fixtures.py``.
These fixtures never import application code and never touch a database.
"""
