"""python fundamental_engine/scripts/init_watchlist.py [--apply]   (default: dry run; needs LIBSQL_URL + token)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import TursoClient
from core.watchlist import init_watchlist

if __name__ == "__main__":
    print(init_watchlist(TursoClient(), dry_run="--apply" not in sys.argv))
