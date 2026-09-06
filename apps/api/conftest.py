"""
Makes `app` importable no matter how the suite is started.

pytest's default (prepend) import mode puts the directory containing this
conftest at the front of sys.path, so `from app.main import app` resolves
under bare `pytest`, `python -m pytest`, and IDE test runners alike.

Without it only `python -m pytest` works, because that form adds the
current directory to sys.path itself. That is why the suite passed locally
while CI -- which runs bare `pytest` -- collected 0 items and exited 2 with
`ModuleNotFoundError: No module named 'app'`. It went unnoticed because the
workflow triggered only on [main, develop] while the repo's branch is
master, so CI had never actually run (see 0778230).
"""
