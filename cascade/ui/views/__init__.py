"""cascade.ui.views — view modules for each console screen.

Each module renders one screen and accepts an :class:`APIClient` so the view
is testable without standing up a real Streamlit runtime (use
``streamlit.testing.v1.AppTest`` for that — see
``tests/unit/test_ui_views.py``).
"""
