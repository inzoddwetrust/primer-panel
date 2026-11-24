"""The core of the Panel: state, database, Redis, errors, client address, limits.

Translated from velo and aivis onto the blank's form: nothing here is created
at import time; ``app.main.create_app`` builds the state and every request
reaches it through FastAPI dependencies (``app.core.state``).
"""
