#!/bin/sh
set -e
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

TARGET_DATE="${1:-2026-07-18}"
LIMIT="${2:-50}"
MODE="${3:-dry_run}"

echo "=== 1. Wiping database tables ==="
uv run python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, MetaData
url = os.environ.get('WALLET_V2__DATABASE__URL')
if url:
    engine = create_engine(url)
    meta = MetaData()
    meta.reflect(bind=engine)
    meta.drop_all(bind=engine)
print('Database tables wiped successfully.')
"

echo "=== 2. Re-applying database migrations ==="
uv run alembic upgrade head

echo "=== 3. Syncing Wallet catalog ==="
uv run wallet-v2 sync-catalog

echo "=== 4. Processing emails for ${TARGET_DATE} (mode: ${MODE}, limit: ${LIMIT}) ==="
uv run wallet-v2 run --label "reprocess-${TARGET_DATE}" --mode "${MODE}" --on-date "${TARGET_DATE}" --limit "${LIMIT}"

echo "=== Reset & reprocess complete ==="
