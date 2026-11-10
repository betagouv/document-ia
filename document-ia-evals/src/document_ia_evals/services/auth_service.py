"""Authentication and RBAC service for Document IA Evals."""

import logging
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import desc, func, select

from document_ia_evals.database.connection import get_session
from document_ia_evals.database.models import EvalsAccessLog, EvalsUser, UserRole

logger = logging.getLogger(__name__)

INITIAL_ADMIN_EMAILS = {
    "nicolas.sagon@beta.gouv.fr",
    "nicolas.sagon@ext.beta.gouv.fr",
}


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
    """Update role or active status of an authorized user."""
    with get_session() as session:
        stmt = select(EvalsUser).where(
            func.lower(EvalsUser.email) == user_id_or_email.strip().lower()
        )
        user = session.scalars(stmt).first()
        if not user:
            raise ValueError(f"Utilisateur introuvable : {user_id_or_email}")

        if role is not None:
            if role not in (UserRole.ADMIN.value, UserRole.USER.value):
                raise ValueError(f"Rôle invalide : {role}")
            user.role = role

        if is_active is not None:
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
