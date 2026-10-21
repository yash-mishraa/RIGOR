import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import session_dependency
from app.core.rate_limit import enforce_shared_limit
from app.models import DemoVisitorSession


def _signature(session_id: UUID) -> str:
    return hmac.new(
        settings.demo_session_secret.encode(), session_id.bytes, hashlib.sha256
    ).hexdigest()


def _decode_cookie(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        raw_id, supplied_signature = value.split(".", 1)
        session_id = UUID(raw_id)
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(_signature(session_id), supplied_signature):
        return None
    return session_id


async def demo_session_dependency(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(session_dependency),
) -> UUID:
    """Validate an opaque signed cookie against an unexpired server-side row."""
    now = datetime.now(UTC)
    session_id = _decode_cookie(request.cookies.get(settings.demo_cookie_name))
    if session_id:
        visitor = await session.scalar(
            select(DemoVisitorSession).where(
                DemoVisitorSession.id == session_id,
                DemoVisitorSession.expires_at > now,
            )
        )
        if visitor is not None:
            return visitor.id

    client_host = request.client.host if request.client else "unknown"
    ip_subject = hmac.new(
        settings.demo_session_secret.encode(), client_host.encode(), hashlib.sha256
    ).hexdigest()
    await enforce_shared_limit(session, f"ip-{ip_subject}", "demo-session-init", 5)
    await session.execute(
        delete(DemoVisitorSession).where(DemoVisitorSession.expires_at <= now)
    )
    session_id = uuid4()
    session.add(
        DemoVisitorSession(
            id=session_id,
            expires_at=now + timedelta(days=settings.demo_session_days),
        )
    )
    await session.commit()
    response.set_cookie(
        settings.demo_cookie_name,
        f"{session_id}.{_signature(session_id)}",
        max_age=settings.demo_session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.demo_cookie_secure,
        samesite=settings.demo_cookie_samesite.lower(),
        path="/",
    )
    return session_id


async def require_accessible_job(session: AsyncSession, job_id: UUID, visitor_id: UUID):
    from app.models import JobPost

    job = await session.scalar(
        select(JobPost).where(
            JobPost.id == job_id,
            (JobPost.owner_session_id == visitor_id)
            | (
                JobPost.owner_session_id.is_(None)
                & (JobPost.source_type != "user_import")
            ),
        )
    )
    if job is None:
        raise HTTPException(404, "Job not found")
    return job
