"""Regressions for the Codex review of the ProConnect/RBAC pull request.

1. Pages must pair the endpoint with its own credential, never send the server
   default key to a custom environment.
2. Privileged user-management callbacks must re-check the acting administrator
   against the database, not the cached session role.
3. Federated logout must keep the deployment redirect when no override is set.
"""

import threading
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import sessionmaker

from document_ia_evals.database.models import Base, EvalsAccessLog, EvalsUser
from document_ia_evals.services.administration_service import get_current_config
from document_ia_evals.services.auth_service import (
    add_evals_user,
    assert_active_admin,
    update_evals_user,
)
from document_ia_evals.services.create_dataset_service import process_files_parallel_v2
from document_ia_evals.services.create_predictions_service import (
    run_workflow_on_dataset_v2,
)
from document_ia_evals.utils.config import config

DEFAULT_KEY = "secret-server-default-key"
CUSTOM_URL = "https://staging.document-ia.gouv.fr"
CUSTOM_KEY = "key-for-staging-only"


@pytest.fixture
def in_memory_db():
    """Isolated SQLite database for authorization tests."""
    engine = create_engine("sqlite:///:memory:")
    from typing import cast

    Base.metadata.create_all(
        bind=engine,
        tables=cast(list[Table], [EvalsUser.__table__, EvalsAccessLog.__table__]),
    )
    Session = sessionmaker(bind=engine)

    @contextmanager
    def mock_get_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    with patch(
        "document_ia_evals.services.auth_service.get_session",
        side_effect=mock_get_session,
    ):
        yield


# --------------------------------------------------------------------------
# 1. Endpoint / credential pairing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "page",
    ["create_dataset_v2", "create_predictions_v2", "prompt_playground"],
)
def test_pages_resolve_key_from_session_not_global_config(page: str):
    """The three pages must read the session key, not config.DOCUMENT_IA_API_KEY."""
    from importlib import import_module

    module = import_module(f"document_ia_evals.pages.{page}")
    session = {
        "custom_document_ia_url": CUSTOM_URL,
        "custom_document_ia_api_key": CUSTOM_KEY,
    }
    with patch.object(config, "DOCUMENT_IA_API_KEY", DEFAULT_KEY):
        with patch("streamlit.session_state", session):
            assert module.get_current_config()["api_key"] == CUSTOM_KEY
            assert module.get_current_config()["base_url"] == CUSTOM_URL


def test_custom_environment_never_receives_default_key():
    """A custom URL without its own key yields an empty key, not the default."""
    with patch.object(config, "DOCUMENT_IA_API_KEY", DEFAULT_KEY):
        with patch(
            "streamlit.session_state", {"custom_document_ia_url": CUSTOM_URL}
        ):
            cfg = get_current_config()
            assert cfg["base_url"] == CUSTOM_URL
            assert cfg["api_key"] == ""


def test_dataset_workers_forward_paired_endpoint():
    """Worker threads have no script context, so base_url must be forwarded."""
    seen: list[tuple[str | None, str | None]] = []
    lock = threading.Lock()

    def fake_execute(**kwargs):
        with lock:
            seen.append((kwargs.get("base_url"), kwargs.get("api_token")))
        return {"execution_id": "exec-1"}

    class FakeFile:
        name = "doc.pdf"

        def getvalue(self):
            return b"%PDF-1.4"

    with patch(
        "document_ia_evals.services.create_dataset_service.execute_workflow_v2",
        side_effect=fake_execute,
    ):
        with patch(
            "document_ia_evals.services.create_dataset_service.wait_for_execution",
            return_value=None,
        ):
            with patch.object(config, "S3_BUCKET_NAME", "bucket"):
                process_files_parallel_v2(
                    files=[FakeFile()],
                    api_key=CUSTOM_KEY,
                    workflow_id="wf",
                    s3_prefix="prefix",
                    n_workers=1,
                    base_url=CUSTOM_URL,
                )

    assert seen == [(CUSTOM_URL, CUSTOM_KEY)]


def test_prediction_workers_forward_paired_endpoint():
    """Same guarantee for the predictions worker pool."""
    seen: list[tuple[str | None, str | None]] = []
    lock = threading.Lock()

    def fake_execute(**kwargs):
        with lock:
            seen.append((kwargs.get("base_url"), kwargs.get("api_token")))
        return {"execution_id": "exec-1"}

    class FakeTask:
        id = 1
        data = {"pdf": "https://label-studio.test/doc.pdf"}

    class FakeTasks:
        def list(self, **kwargs):
            return [FakeTask()]

    class FakeClient:
        tasks = FakeTasks()

    with patch(
        "document_ia_evals.services.create_predictions_service.execute_workflow_v2",
        side_effect=fake_execute,
    ):
        with patch(
            "document_ia_evals.services.create_predictions_service."
            "extract_s3_url_from_task_url",
            return_value="s3://bucket/key.pdf",
        ):
            with patch(
                "document_ia_evals.services.create_predictions_service.download_from_s3",
                return_value=(b"%PDF-1.4", "doc.pdf"),
            ):
                with patch(
                    "document_ia_evals.services.create_predictions_service."
                    "wait_for_execution",
                    return_value=None,
                ):
                    run_workflow_on_dataset_v2(
                        workflow_id="wf",
                        project_id=1,
                        api_key=CUSTOM_KEY,
                        ls_client=FakeClient(),
                        n_workers=1,
                        tasks=[FakeTask()],
                        base_url=CUSTOM_URL,
                    )

    assert seen == [(CUSTOM_URL, CUSTOM_KEY)]


# --------------------------------------------------------------------------
# 2. Acting administrator re-check
# --------------------------------------------------------------------------


def test_active_admin_passes_guard(in_memory_db):
    add_evals_user("root-admin@beta.gouv.fr", role="admin")
    assert_active_admin("root-admin@beta.gouv.fr")


def test_demoted_admin_rejected_even_with_stale_session_role(in_memory_db):
    """A page left open must not keep working after the actor is demoted."""
    add_evals_user("keeper@beta.gouv.fr", role="admin")
    actor = add_evals_user("actor@beta.gouv.fr", role="admin")
    update_evals_user(actor.email, role="user")

    # The session still claims admin: the guard must consult the database.
    with patch("streamlit.session_state", {"current_user_role": "admin"}):
        with pytest.raises(PermissionError):
            assert_active_admin("actor@beta.gouv.fr")


def test_disabled_admin_rejected(in_memory_db):
    add_evals_user("keeper2@beta.gouv.fr", role="admin")
    actor = add_evals_user("disabled@beta.gouv.fr", role="admin")
    update_evals_user(actor.email, is_active=False)

    with pytest.raises(PermissionError):
        assert_active_admin("disabled@beta.gouv.fr")


def test_unknown_and_empty_actor_rejected(in_memory_db):
    with pytest.raises(PermissionError):
        assert_active_admin("nobody@beta.gouv.fr")
    with pytest.raises(PermissionError):
        assert_active_admin(None)
    with pytest.raises(PermissionError):
        assert_active_admin("")


def test_role_change_callback_blocks_demoted_actor(in_memory_db):
    """The Streamlit callback must refuse the mutation, not just warn on rerun."""
    from document_ia_evals.pages import admin_users

    add_evals_user("keeper3@beta.gouv.fr", role="admin")
    actor = add_evals_user("stale@beta.gouv.fr", role="admin")
    target = add_evals_user("target@beta.gouv.fr", role="user")
    update_evals_user(actor.email, role="user")

    session = {
        "current_user_email": actor.email,
        "current_user_role": "admin",
        "role_select_widget": "admin",
    }
    with patch("streamlit.session_state", session):
        with patch.object(admin_users.st, "toast") as toast:
            with patch.object(admin_users.st, "error") as error:
                admin_users._handle_role_change(target.email, "role_select_widget")

    toast.assert_not_called()
    error.assert_called_once()
    assert target.role == "user"


def test_dialog_mutations_recheck_acting_admin(in_memory_db):
    """Dialog reruns skip app.main() and the page guard, so each mutation checks.

    Covers organization, API-key and webhook mutations reached from a dialog.
    """
    from document_ia_evals.pages import admin_api_keys

    add_evals_user("keeper4@beta.gouv.fr", role="admin")
    actor = add_evals_user("dialog-actor@beta.gouv.fr", role="admin")
    update_evals_user(actor.email, role="user")

    with patch(
        "streamlit.session_state",
        {"current_user_email": actor.email, "current_user_role": "admin"},
    ):
        with pytest.raises(PermissionError):
            admin_api_keys._require_active_admin()


@pytest.mark.parametrize(
    "mutation",
    [
        "create_organization",
        "delete_organization",
        "create_api_key",
        "delete_api_key",
        "update_api_key_status",
        "create_webhook",
        "delete_webhook",
    ],
)
def test_every_admin_api_key_mutation_is_guarded(mutation: str):
    """Each privileged call site must be preceded by the actor re-check."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "document_ia_evals"
        / "pages"
        / "admin_api_keys.py"
    ).read_text(encoding="utf-8")
    lines = source.splitlines()

    call_lines = [
        i
        for i, line in enumerate(lines)
        if f"{mutation}(" in line and "import" not in line and "def " not in line
    ]
    assert call_lines, f"no call site found for {mutation}"
    for i in call_lines:
        preceding = "\n".join(lines[max(0, i - 6) : i])
        assert "_require_active_admin()" in preceding, (
            f"{mutation} at line {i + 1} is not guarded"
        )


# --------------------------------------------------------------------------
# 3. Federated logout redirect
# --------------------------------------------------------------------------


def test_workflow_cache_is_keyed_by_active_configuration():
    """Switching environments must not reuse the previous endpoint's workflows."""
    from document_ia_evals.components import workflow_configurator as wc

    with patch(
        "streamlit.session_state",
        {"custom_document_ia_url": CUSTOM_URL, "custom_document_ia_api_key": CUSTOM_KEY},
    ):
        custom_fp = wc._config_fingerprint()

    with patch("streamlit.session_state", {}):
        default_fp = wc._config_fingerprint()

    assert custom_fp != default_fp

    # Same endpoint, different credential: still a different configuration.
    with patch(
        "streamlit.session_state",
        {"custom_document_ia_url": CUSTOM_URL, "custom_document_ia_api_key": "other"},
    ):
        assert wc._config_fingerprint() != custom_fp


def test_reset_clears_cached_workflows_and_derived_widgets():
    from document_ia_evals.components import workflow_configurator as wc

    session = {
        "workflows_data": {"data": [{"id": "old-env-workflow"}]},
        "workflow_selector_dataset_v2": {"id": "old-env-workflow"},
        "last_default_workflow_id_dataset_v2": "old-env-workflow",
        "extract_data_document_type_dataset_v2": "old_type",
        "current_user_email": "admin@beta.gouv.fr",
        "custom_document_ia_url": CUSTOM_URL,
    }
    with patch("streamlit.session_state", session):
        wc._reset_workflow_state("_dataset_v2")

    assert "workflows_data" not in session
    assert "workflow_selector_dataset_v2" not in session
    assert "extract_data_document_type_dataset_v2" not in session
    # Identity and configuration are not workflow widget state.
    assert session["current_user_email"] == "admin@beta.gouv.fr"
    assert session["custom_document_ia_url"] == CUSTOM_URL


def test_reset_with_empty_suffix_preserves_unrelated_session_keys():
    """An empty key_suffix must not act as a match-everything suffix."""
    from document_ia_evals.components import workflow_configurator as wc

    session = {
        "workflows_data": {"data": []},
        "workflow_selector": {"id": "wf"},
        "current_user_email": "admin@beta.gouv.fr",
        "current_user_role": "admin",
        "selected_org_name": "Acme",
    }
    with patch("streamlit.session_state", session):
        wc._reset_workflow_state("")

    assert "workflows_data" not in session
    assert "workflow_selector" not in session
    assert session["current_user_email"] == "admin@beta.gouv.fr"
    assert session["current_user_role"] == "admin"
    assert session["selected_org_name"] == "Acme"


def test_configurator_refetches_after_environment_switch():
    """End-to-end: the second render fetches from the newly selected endpoint."""
    from document_ia_evals.components import workflow_configurator as wc

    session: dict = {}
    calls: list[str | None] = []

    def fake_get_workflows(api_key=None, base_url=None):
        calls.append(api_key)
        return {"data": [{"id": f"wf-{api_key}", "name": "wf", "steps": []}]}

    with patch.object(wc, "get_workflows", side_effect=fake_get_workflows):
        with patch("streamlit.session_state", session):
            with patch.object(wc.st, "spinner"):
                with patch.object(wc.st, "selectbox", side_effect=lambda *a, **k: k["options"][0]):
                    with patch.object(wc.st, "columns", return_value=[_Null(), _Null()]):
                        with patch.object(wc.st, "markdown"), patch.object(wc.st, "write"), patch.object(
                            wc.st, "subheader"
                        ), patch.object(wc.st, "warning"), patch.object(wc.st, "error"):
                            session.update(
                                custom_document_ia_url=CUSTOM_URL,
                                custom_document_ia_api_key=CUSTOM_KEY,
                            )
                            wc.render_workflow_configurator(CUSTOM_KEY, key_suffix="_t")
                            # Administrator switches back to the default environment.
                            session.pop("custom_document_ia_url")
                            session.pop("custom_document_ia_api_key")
                            wc.render_workflow_configurator(DEFAULT_KEY, key_suffix="_t")

    assert calls == [CUSTOM_KEY, DEFAULT_KEY]


class _Null:
    """Context-manager stand-in for a Streamlit column."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_post_logout_override_is_optional_by_default():
    """Unset by default so Streamlit's deployment redirect is preserved."""
    assert config.PROCONNECT_POST_LOGOUT_REDIRECT_URI is None


def _build_logout_url(post_logout_setting: str | None, computed: str) -> str:
    """Exercise the patched build_logout_url on the real Streamlit routes module.

    The module attribute must be replaced directly: `import a.b.c` resolves via
    the parent package attribute, so a sys.modules entry alone is not picked up.
    """
    from document_ia_evals.utils import auth_secrets
    import streamlit.web.server.starlette.starlette_auth_routes as s_routes

    captured: dict[str, str] = {}

    def original_build_logout_url(**kwargs):
        captured.update(kwargs)
        return kwargs["post_logout_redirect_uri"]

    with patch.object(s_routes, "build_logout_url", original_build_logout_url):
        with patch.object(s_routes, "_proconnect_logout_patched", False, create=True):
            with patch.object(
                auth_secrets.config,
                "PROCONNECT_POST_LOGOUT_REDIRECT_URI",
                post_logout_setting,
            ):
                auth_secrets.patch_streamlit_oidc()
                assert s_routes._proconnect_logout_patched is True
                s_routes.build_logout_url(
                    end_session_endpoint="https://proconnect.test/logout",
                    client_id="client",
                    post_logout_redirect_uri=computed,
                    id_token=None,
                )

    return captured["post_logout_redirect_uri"]


def test_logout_keeps_deployment_redirect_when_unset():
    hosted = "https://evals.document-ia.gouv.fr/oauth2callback"
    assert _build_logout_url(None, hosted) == hosted


def test_logout_honours_explicit_override():
    explicit = "https://evals.document-ia.gouv.fr/signed-out"
    assert (
        _build_logout_url(explicit, "https://evals.document-ia.gouv.fr/oauth2callback")
        == explicit
    )
