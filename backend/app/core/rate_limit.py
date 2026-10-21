from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RequestRateBucket


async def enforce_shared_limit(
    session: AsyncSession,
    visitor_id: object,
    operation: str,
    limit: int,
    *,
    window_seconds: int = 60,
) -> None:
    """Atomically count a visitor operation in the shared relational database."""
    now = datetime.now(UTC)
    window = int(now.timestamp()) // window_seconds
    bucket_key = f"{operation}:{visitor_id}:{window}"
    expires_at = datetime.fromtimestamp((window + 2) * window_seconds, tz=UTC)
    values = {"bucket_key": bucket_key, "hits": 1, "expires_at": expires_at}
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        statement = pg_insert(RequestRateBucket).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(RequestRateBucket).values(**values)
    else:
        raise RuntimeError(f"Shared request limits are unsupported for database dialect {dialect}")
    statement = statement.on_conflict_do_update(
        index_elements=[RequestRateBucket.bucket_key],
        set_={"hits": RequestRateBucket.hits + 1, "expires_at": expires_at},
    ).returning(RequestRateBucket.hits)
    hits = (await session.execute(statement)).scalar_one()
    await session.execute(
        delete(RequestRateBucket).where(RequestRateBucket.expires_at < now)
    )
    await session.commit()
    if hits > limit:
        retry_after = max(1, (window + 1) * window_seconds - int(now.timestamp()))
        raise HTTPException(
            429,
            "Demo request limit reached; wait briefly and try again.",
            headers={"Retry-After": str(retry_after)},
        )
