from __future__ import annotations

from app.db.session import get_async_session

get_db = get_async_session
