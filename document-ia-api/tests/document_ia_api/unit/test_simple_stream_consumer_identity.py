"""Unit tests for per-instance consumer naming (issue #112)."""

from __future__ import annotations

import os
import socket

import pytest

from document_ia_api.infra.redis.simple_stream_consumer import (
    build_instance_consumer_name,
)


@pytest.fixture(autouse=True)
def mock_api_key_service_auth() -> None:
    """Naming tests do not exercise API authentication or the DB."""


def test_consumer_name_binds_base_to_instance_identity() -> None:
    base = "api-webhook-consumer"
    assert build_instance_consumer_name(base) == (
        f"{base}-{socket.gethostname()}-{os.getpid()}"
    )


def test_consumer_name_is_stable_within_process() -> None:
    assert build_instance_consumer_name(
        "api-webhook-consumer"
    ) == build_instance_consumer_name("api-webhook-consumer")


def test_consumer_names_differ_across_instances() -> None:
    # Two API instances in one test process differ by base name; in
    # production the hostname and pid parts differ as well.
    assert build_instance_consumer_name(
        "api-webhook-consumer-a"
    ) != build_instance_consumer_name("api-webhook-consumer-b")


def test_consumer_name_has_no_whitespace() -> None:
    name = build_instance_consumer_name("api-webhook-consumer")
    assert name.strip() == name
    assert " " not in name
