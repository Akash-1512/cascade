"""cascade operator console.

Streamlit-based UI that reads from the cascade REST API. Lives entirely in
read-only territory — drafts, commits, target changes, and check-ins flow
through the MCP server because that's where the agent loop lives. The UI
is a viewer for what the agents have produced.

Run::

    streamlit run cascade/ui/app.py

Set ``CASCADE_UI_API_URL`` to point at the REST API (defaults to
``http://localhost:8000``).
"""
