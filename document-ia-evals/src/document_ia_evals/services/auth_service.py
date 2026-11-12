"""Authentication and RBAC service for Document IA Evals."""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Sequence
from urllib.parse import urlparse

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from document_ia_evals.database.connection import get_session
from document_ia_evals.database.models import EvalsAccessLog, EvalsUser, UserRole

logger = logging.getLogger(__name__)

INITIAL_ADMIN_EMAILS = {
    "nicolas.sagon@beta.gouv.fr",
    "nicolas.sagon@ext.beta.gouv.fr",
}


def is_local_bypass_allowed() -> bool:
    """Check if offline local development bypass is safely permitted.

    Strictly rejected if running in hosted/containerized environments or if
    PROCONNECT_REDIRECT_URI does not point to localhost / 127.0.0.1.
    """
    from document_ia_evals.utils.config import config

    if not config.AUTH_BYPASS_LOCAL:
        return False
    if os.getenv("SCALINGO_APP") or os.getenv("CONTAINER"):
        logger.error(
            "AUTH_BYPASS_LOCAL is strictly forbidden in hosted environments (SCALINGO_APP/CONTAINER)."
        )
        return False
    redirect_uri = config.PROCONNECT_REDIRECT_URI or ""
    parsed = urlparse(redirect_uri)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        logger.error(
            "AUTH_BYPASS_LOCAL is only allowed when PROCONNECT_REDIRECT_URI points to localhost or 127.0.0.1."
        )
        return False
    return True


def _count_active_admins(session: Session) -> int:
    """Count number of active users with admin role."""
    stmt = (
        select(func.count())
        .select_from(EvalsUser)
        .where(
            EvalsUser.role == UserRole.ADMIN.value,
            EvalsUser.is_active.is_(True),
        )
    )
    return session.scalar(stmt) or 0


def _lock_active_admins(session: Session) -> None:
    """Serialize the count-and-mutate that protects the last active administrator.

    Two administrators demoting or disabling each other concurrently would
    otherwise both read a count of two and both commit, leaving no active
    administrator. Locking the current active-admin rows before counting makes
    the second transaction wait and then observe the first one's commit.

    PostgreSQL only: SQLite (used by the unit tests) has no row-level locking and
    already serializes writers at the database level.
    """
    if session.get_bind().dialect.name != "postgresql":
        return

    session.scalars(
        select(EvalsUser)
        .where(
            EvalsUser.role == UserRole.ADMIN.value,
            EvalsUser.is_active.is_(True),
        )
        .order_by(EvalsUser.id)
        .with_for_update()
    ).all()


def record_login_event(
    email: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Record an authentication event in evals_access_logs and update last_login_at.

    This function is called EXCLUSIVELY during the OIDC token exchange callback
    (/oauth2callback) upon receiving a verified access token from ProConnect.
    It is NEVER called on page refreshes (F5), page navigations, or widget reruns.
    """
    clean_email = email.strip().lower()

    with get_session() as session:
        stmt = select(EvalsUser).where(func.lower(EvalsUser.email) == clean_email)
        user = session.scalars(stmt).first()

        # Resilient auto-provisioning for initial project administrators
        if not user and clean_email in INITIAL_ADMIN_EMAILS:
            logger.info("Auto-provisioning initial admin user: %s", clean_email)
            user = EvalsUser(
                email=clean_email,
                role=UserRole.ADMIN.value,
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)

        if not user:
            logger.warning(
                "OAuth login denied: user %s not found in database", clean_email
            )
            log = EvalsAccessLog(
                user_id=None,
                email=clean_email,
                action="access_denied_unknown_user",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            session.add(log)
            session.commit()
            return

        if not user.is_active:
            logger.warning("OAuth login denied: user %s is disabled", clean_email)
            log = EvalsAccessLog(
                user_id=user.id,
                email=clean_email,
                action="access_denied_disabled_user",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            session.add(log)
            session.commit()
            return

        # Successful login
        user.last_login_at = datetime.now(timezone.utc)
        log = EvalsAccessLog(
            user_id=user.id,
            email=clean_email,
            action="login_success",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.add(log)
        session.commit()


def verify_user_access(
    email: str,
) -> tuple[bool, EvalsUser | None, str]:
    """Verify if a user identified by email is currently allowed to access the application.

    This function acts as a pure read-only authorization guard. It NEVER writes to
    evals_access_logs to prevent log flooding during page reloads (F5) or user interactions.
    """
    clean_email = email.strip().lower()

    with get_session() as session:
        stmt = select(EvalsUser).where(func.lower(EvalsUser.email) == clean_email)
        user = session.scalars(stmt).first()

        if not user:
            if clean_email in INITIAL_ADMIN_EMAILS:
                logger.info("Auto-provisioning initial admin user: %s", clean_email)
                user = EvalsUser(
                    email=clean_email,
                    role=UserRole.ADMIN.value,
                    is_active=True,
                )
                session.add(user)
                session.commit()
                session.refresh(user)
            else:
                return (
                    False,
                    None,
                    f"Accès refusé : l'adresse '{clean_email}' n'est pas habilitée sur Document IA.",
                )

        if not user.is_active:
            return (
                False,
                None,
                "Accès refusé : votre compte a été désactivé par un administrateur.",
            )

        return True, user, "Accès autorisé."


def record_logout(
    email: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Record a user logout event in access logs."""
    clean_email = email.strip().lower()
    with get_session() as session:
        stmt = select(EvalsUser).where(func.lower(EvalsUser.email) == clean_email)
        user = session.scalars(stmt).first()

        log = EvalsAccessLog(
            user_id=user.id if user else None,
            email=clean_email,
            action="logout",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.add(log)
        session.commit()


def list_evals_users(limit: int = 200) -> Sequence[EvalsUser]:
    """Retrieve list of authorized users."""
    with get_session() as session:
        stmt = select(EvalsUser).order_by(desc(EvalsUser.created_at)).limit(limit)
        return session.scalars(stmt).all()


def assert_active_admin(email: str | None) -> None:
    """Reject a privileged mutation unless the actor is an active admin right now.

    Streamlit runs widget callbacks before the script reruns, so a page left open
    can invoke a mutation after the account was demoted or disabled. The cached
    session role is not evidence of current rights: this reads the database.
    """
    clean_email = (email or "").strip().lower()
    if not clean_email:
        raise PermissionError("Action refusée : administrateur non identifié.")

    if is_local_bypass_allowed():
        return

    with get_session() as session:
        actor = session.scalars(
            select(EvalsUser).where(func.lower(EvalsUser.email) == clean_email)
        ).first()

    if actor is None or not actor.is_active or actor.role != UserRole.ADMIN.value:
        logger.warning(
            "Rejected privileged user-management action for non-admin actor: %s",
            clean_email,
        )
        raise PermissionError(
            "Action refusée : vos droits d'administration ne sont plus actifs."
        )


def get_evals_user_by_email(email: str) -> EvalsUser | None:
    """Get user by email address."""
    clean_email = email.strip().lower()
    with get_session() as session:
        stmt = select(EvalsUser).where(func.lower(EvalsUser.email) == clean_email)
        return session.scalars(stmt).first()


def add_evals_user(
    email: str,
    role: str = UserRole.USER.value,
) -> EvalsUser:
    """Add a new authorized user."""
    clean_email = email.strip().lower()
    if role not in (UserRole.ADMIN.value, UserRole.USER.value):
        raise ValueError(f"Rôle invalide: {role}")

    with get_session() as session:
        existing = session.scalars(
            select(EvalsUser).where(func.lower(EvalsUser.email) == clean_email)
        ).first()
        if existing:
            raise ValueError(f"L'utilisateur {clean_email} existe déjà.")

        user = EvalsUser(
            email=clean_email,
            role=role,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def update_evals_user(
    user_id_or_email: str,
    role: str | None = None,
    is_active: bool | None = None,
) -> EvalsUser:
    """Update role or active status of an authorized user (supports UUID or email)."""
    with get_session() as session:
        user = None
        target = user_id_or_email.strip()
        try:
            parsed_uuid = uuid.UUID(target)
            user = session.scalars(
                select(EvalsUser).where(EvalsUser.id == parsed_uuid)
            ).first()
        except (ValueError, AttributeError):
            pass

        if not user:
            user = session.scalars(
                select(EvalsUser).where(func.lower(EvalsUser.email) == target.lower())
            ).first()

        if not user:
            raise ValueError(f"Utilisateur introuvable : {user_id_or_email}")

        is_currently_active_admin = (
            user.role == UserRole.ADMIN.value and user.is_active is True
        )

        if role is not None:
            if role not in (UserRole.ADMIN.value, UserRole.USER.value):
                raise ValueError(f"Rôle invalide : {role}")
            if is_currently_active_admin and role != UserRole.ADMIN.value:
                _lock_active_admins(session)
                if _count_active_admins(session) <= 1:
                    raise ValueError(
                        "Impossible de rétrograder le dernier administrateur actif."
                    )
            user.role = role

        if is_active is not None:
            if is_currently_active_admin and is_active is False:
                _lock_active_admins(session)
                if _count_active_admins(session) <= 1:
                    raise ValueError(
                        "Impossible de désactiver le dernier administrateur actif."
                    )
            user.is_active = is_active

        session.commit()
        session.refresh(user)
        return user


def delete_evals_user(email: str) -> bool:
    """Delete an authorized user."""
    clean_email = email.strip().lower()
    with get_session() as session:
        stmt = select(EvalsUser).where(func.lower(EvalsUser.email) == clean_email)
        user = session.scalars(stmt).first()
        if not user:
            return False

        if user.role == UserRole.ADMIN.value and user.is_active is True:
            _lock_active_admins(session)
            if _count_active_admins(session) <= 1:
                raise ValueError(
                    "Impossible de supprimer le dernier administrateur actif."
                )

        session.delete(user)
        session.commit()
        return True


def list_recent_access_logs(limit: int = 50) -> Sequence[EvalsAccessLog]:
    """Retrieve recent access logs."""
    with get_session() as session:
        stmt = (
            select(EvalsAccessLog)
            .order_by(desc(EvalsAccessLog.created_at))
            .limit(limit)
        )
        return session.scalars(stmt).all()
