"""Prepare the configured Turso database before deploying to Vercel."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import migrate_db


if __name__ == "__main__":
    migrate_db()
    print("Banco Turso preparado para o deploy.")
