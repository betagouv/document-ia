"""Safe HTTPX async transport with anti-SSRF, socket pinning, and redirect blocking."""

import asyncio
import ipaddress
import logging
import socket
import ssl
from typing import Any, Iterable, Union

import httpcore
from httpcore._backends.auto import AutoBackend
import httpx
from httpx import create_ssl_context

from document_ia_infra.core.network.ip_validator import (
    validate_hostname,
    validate_ip,
)
from document_ia_infra.exception.security_exception import (
    BlockedAddressException,
    DisallowedRedirectException,
    InvalidProtocolException,
)

logger = logging.getLogger(__name__)

DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)


async def resolve_and_pin_ip(
    hostname: str,
    port: int,
    allow_local: bool = False,
) -> str:
    """Resolve DNS records for hostname and ensure ALL returned IPs are safe.

    Returns the first validated IP address to pin the connection.

    Raises:
        BlockedAddressException: If resolution fails or any resolved IP is forbidden.
    """
    validate_hostname(hostname, allow_local=allow_local)

    # Check if hostname is already a raw IP literal
    try:
        ip_obj = ipaddress.ip_address(hostname)
        validate_ip(ip_obj, allow_local=allow_local)
        return hostname
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        addr_infos = await loop.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise BlockedAddressException(
            f"DNS resolution failed for hostname '{hostname}': {exc}"
        ) from exc

    if not addr_infos:
        raise BlockedAddressException(f"No DNS records found for hostname '{hostname}'")

    # Anti-DNS Rebinding: ALL resolved addresses must be strictly safe
    validated_ips: list[str] = []
    for info in addr_infos:
        sockaddr = info[4]
        raw_ip = str(sockaddr[0])
        validate_ip(raw_ip, allow_local=allow_local)
        validated_ips.append(raw_ip)

    pinned_ip = validated_ips[0]
    logger.debug(
        "DNS resolution for %s pinned to IP: %s (total valid IPs: %d)",
        hostname,
        pinned_ip,
        len(validated_ips),
    )
    return pinned_ip


class SafeAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Network backend wrapping the default backend with socket pinning and SSRF checks."""

    def __init__(
        self,
        backend: httpcore.AsyncNetworkBackend | None = None,
        allow_local: bool = False,
    ) -> None:
        self.allow_local = allow_local
        if backend is not None:
            self._backend: httpcore.AsyncNetworkBackend = backend
        else:
            self._backend = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[
            tuple[int, int, int]
            | tuple[int, int, bytes | bytearray]
            | tuple[int, int, None, int]
        ]
        | None = None,
    ) -> httpcore.AsyncNetworkStream:
        pinned_ip = await resolve_and_pin_ip(host, port, allow_local=self.allow_local)
        return await self._backend.connect_tcp(
            host=pinned_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[
            tuple[int, int, int]
            | tuple[int, int, bytes | bytearray]
            | tuple[int, int, None, int]
        ]
        | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise BlockedAddressException("Unix domain sockets are not permitted.")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class SafeAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX async transport enforcing HTTPS, anti-SSRF socket pinning, and blocking redirects."""

    def __init__(
        self,
        verify: Union[ssl.SSLContext, str, bool] = True,
        cert: Any = None,
        trust_env: bool = True,
        http1: bool = True,
        http2: bool = False,
        limits: httpx.Limits = DEFAULT_LIMITS,
        allow_http: bool = False,
        allow_local: bool = False,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
        **kwargs: Any,
    ) -> None:
        self.allow_http = allow_http
        self.allow_local = allow_local
        safe_backend = SafeAsyncNetworkBackend(
            backend=network_backend, allow_local=allow_local
        )
        ssl_context = create_ssl_context(verify=verify, cert=cert, trust_env=trust_env)
        super().__init__(
            verify=verify,
            cert=cert,
            trust_env=trust_env,
            http1=http1,
            http2=http2,
            limits=limits,
            **kwargs,
        )
        # Configure connection pool with safe network backend and explicit ssl_context
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=http1,
            http2=http2,
            network_backend=safe_backend,
        )

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        # Strict protocol enforcement
        scheme = request.url.scheme.lower()
        if not self.allow_http and scheme != "https":
            raise InvalidProtocolException(
                f"Disallowed protocol scheme: '{scheme}'. Only HTTPS is permitted."
            )

        # Early hostname check
        validate_hostname(request.url.host, allow_local=self.allow_local)

        # Pre-resolve and validate to catch IP/DNS errors before pool
        port = request.url.port or (443 if scheme == "https" else 80)
        await resolve_and_pin_ip(request.url.host, port, allow_local=self.allow_local)

        response = await super().handle_async_request(request)

        # Strict redirect prohibition (3xx codes)
        if 300 <= response.status_code < 400:
            location = response.headers.get("location", "")
            await response.aclose()
            raise DisallowedRedirectException(
                f"HTTP redirect blocked ({response.status_code}) to: '{location}'"
            )

        return response
