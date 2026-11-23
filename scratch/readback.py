"""Read-only: print the Breakouts table for the latest Phase D session (SELECT only)."""
import sys; sys.path[:0] = [".", "backend"]
import turso_db
from fire_engine import run_phase_d_tracker as R
c = turso_db.get_connection()
class RO:
    def execute(self, q, p=()):
        if not q.lstrip().upper().startswith("SELECT"): raise RuntimeError("read-only")
        return c.execute(q, p)
R.readback(RO())
