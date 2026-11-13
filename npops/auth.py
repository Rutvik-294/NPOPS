"""NPOPS auth & RBAC middleware + session management."""
from __future__ import annotations

import datetime as dt

from .models import User, Session, AuditLog
from .security import hash_password, verify_password, new_session_id, new_token
from .webframe import HTTPError, Response, Request

SESSION_COOKIE = "npops_session"
SESSION_TTL_SECONDS = 12 * 3600

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "planner": {"plan:read", "plan:write", "prod:read", "prod:write",
                "inv:read", "inv:write", "list:read", "track:read", "ops:run"},
    "elf": {"prod:read", "prod:write", "inv:read", "inv:write", "list:read",
            "plan:read"},
    "auditor": {"plan:read", "prod:read", "inv:read", "list:read",
                "track:read", "audit:read"},
    "viewer": {"plan:read", "prod:read", "inv:read", "list:read",
               "track:read"},
}


def has_perm(role: str, perm: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, set())
    return "*" in perms or perm in perms


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit(actor: str, action: str, entity: str = "", entity_id: str = "",
          detail: str = ""):
    AuditLog(actor=actor, action=action, entity=entity,
             entity_id=str(entity_id), detail=detail[:2000],
             ts=utcnow_iso()).insert()


def login(username: str, password: str, ip: str = "") -> tuple[User, Session]:
    user = User.all("username=? AND active=1", (username,))
    if not user or not verify_password(password, user[0].password_hash):
        audit(username or "anonymous", "login_failed", "user", username)
        raise HTTPError(401, "Invalid credentials")
    user = user[0]
    session = Session(
        id=new_session_id(),
        user_id=user.id,
        csrf_token=new_token(24),
        created_at=utcnow_iso(),
        expires_at=(dt.datetime.now(dt.timezone.utc) +
                    dt.timedelta(seconds=SESSION_TTL_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ip=ip,
    )
    session.insert()
    audit(user.username, "login", "user", user.id)
    return user, session


def logout(session_id: str):
    s = Session.get(session_id)
    if s:
        s.delete()


def attach_session(req: Request):
    """Middleware: resolve session -> req.ctx.user (or None)."""
    req.ctx["user"] = None
    req.ctx["session"] = None
    sid = req.cookie(SESSION_COOKIE)
    if not sid:
        return
    s = Session.get(sid)
    if not s or s.expires_at < utcnow_iso():
        return
    user = User.get(s.user_id)
    if not user or not user.active:
        return
    req.ctx["user"] = user
    req.ctx["session"] = s


def require_perm(perm: str):
    """Decorator factory for API handlers."""
    def wrapper(fn):
        def inner(req: Request):
            user = req.ctx.get("user")
            if user is None:
                raise HTTPError(401, "Authentication required")
            if not has_perm(user.role, perm):
                raise HTTPError(403, f"Missing permission {perm}")
            req.ctx["perm"] = perm
            return fn(req)
        return inner
    return wrapper


def check_csrf(req: Request):
    """For state-changing API calls with a session, require CSRF header."""
    if req.method in ("GET", "HEAD", "OPTIONS"):
        return
    session = req.ctx.get("session")
    user = req.ctx.get("user")
    if not (session and user):
        return
    token = req.environ.get("HTTP_X_CSRF_TOKEN", "")
    from .security import constant_time_eq
    if not constant_time_eq(token, session.csrf_token):
        raise HTTPError(403, "CSRF token missing or invalid")


def apply_session_cookie(resp: Response, session: Session):
    resp.set_cookie(SESSION_COOKIE, session.id, max_age=SESSION_TTL_SECONDS)
    resp.headers.append(("X-CSRF-Token", session.csrf_token))
