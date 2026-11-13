"""Anti-SSRF IP address and hostname validator for Document IA."""

import ipaddress
import logging
from typing import Union

from document_ia_infra.exception.security_exception import BlockedAddressException

logger = logging.getLogger(__name__)

# List of blocked IP networks (IPv4 and IPv6) covering RFC 1918, loopback, link-local,
# cloud metadata, carrier-grade NAT (CGNAT), multicast, broadcast, and reserved ranges.
BLOCKED_NETWORKS: list[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = [
    # IPv4 Loopback (RFC 1122)
    ipaddress.ip_network("127.0.0.0/8"),
    # IPv4 RFC 1918 Private Networks
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # IPv4 Link-Local / Cloud Metadata (RFC 3927) - includes 169.254.169.254
    ipaddress.ip_network("169.254.0.0/16"),
    # IPv4 Carrier-Grade NAT (CGNAT, RFC 6598)
    ipaddress.ip_network("100.64.0.0/10"),
    # IPv4 Multicast (RFC 5771)
    ipaddress.ip_network("224.0.0.0/4"),
    # IPv4 Broadcast / Current network / Reserved
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv4 Documentation / Testing / Benchmarking (RFC 5737 / RFC 2544)
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    # IPv6 Loopback & Unspecified (RFC 4291)
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    # IPv6 Unique Local Addresses (ULA, RFC 4193 - fc00::/7) - includes fd00:ec2::254
    ipaddress.ip_network("fc00::/7"),
    # IPv6 Link-Local (RFC 4291)
    ipaddress.ip_network("fe80::/10"),
    # IPv6 Multicast (RFC 4291)
    ipaddress.ip_network("ff00::/8"),
    # IPv6 Documentation (RFC 3849)
    ipaddress.ip_network("2001:db8::/32"),
    # IPv6 Discard-only (RFC 6666)
    ipaddress.ip_network("100::/64"),
]

BLOCKED_HOSTNAMES: set[str] = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "instance-data",
}


def validate_hostname(hostname: str, allow_local: bool = False) -> None:
    """Validate that a hostname is not a prohibited or internal name.

    Raises:
        BlockedAddressException: If the hostname is forbidden.
    """
    if not hostname:
        raise BlockedAddressException("Empty hostname is not allowed.")

    normalized = hostname.strip().lower().rstrip(".")
    if not allow_local and (
        normalized in BLOCKED_HOSTNAMES or normalized.endswith(".localhost")
    ):
        raise BlockedAddressException(
            f"Blocked hostname: '{hostname}' is an internal or reserved name."
        )


def validate_ip(
    ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address, str],
    allow_local: bool = False,
) -> None:
    """Validate that an IP address is a safe, publicly routable address.

    Blocks private RFC 1918, loopback, link-local, cloud metadata, CGNAT,
    multicast, broadcast, reserved ranges, and IPv4-mapped IPv6 internal addresses.
    If allow_local is True, loopback addresses (127.0.0.0/8, ::1) are permitted (for testing).

    Raises:
        BlockedAddressException: If the IP address is in a forbidden range.
        ValueError: If ip is not a syntactically valid IP address.
    """
    if isinstance(ip, str):
        ip_obj = ipaddress.ip_address(ip.strip())
    else:
        ip_obj = ip

    # Handle IPv4-mapped IPv6 addresses (::ffff:x.x.x.x)
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        validate_ip(ip_obj.ipv4_mapped, allow_local=allow_local)
        return

    # If allow_local is enabled (e.g. testing), loopback is permitted
    if allow_local and ip_obj.is_loopback:
        return

    # Built-in properties check
    if (
        ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
        or ip_obj.is_reserved
    ):
        raise BlockedAddressException(
            f"Blocked address: '{ip_obj}' is a private, loopback, link-local, or reserved IP."
        )

    # Check against explicit blocked networks
    for network in BLOCKED_NETWORKS:
        if ip_obj in network:
            raise BlockedAddressException(
                f"Blocked address: '{ip_obj}' belongs to restricted network {network}."
            )


def is_ip_allowed(
    ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address, str],
    allow_local: bool = False,
) -> bool:
    """Return True if an IP address is safe and allowed, False otherwise."""
    try:
        validate_ip(ip, allow_local=allow_local)
        return True
    except BlockedAddressException, ValueError:
        return False
