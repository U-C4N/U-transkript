"""Proxy configurations, compatible with ``youtube_transcript_api.proxies`` 1.2.4.

Without an ``http_client``, utmax.compat sends its requests with the standard library, which
supports ``http://`` proxies (HTTPS traffic is tunnelled through them). For ``https://`` or
SOCKS proxies, pass ``http_client=requests.Session()`` to ``YouTubeTranscriptApi``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict

__all__ = [
    "GenericProxyConfig",
    "InvalidProxyConfig",
    "ProxyConfig",
    "RequestsProxyConfigDict",
    "WebshareProxyConfig",
]


class InvalidProxyConfig(Exception):
    """A proxy configuration is incomplete or cannot be used."""


class RequestsProxyConfigDict(TypedDict):
    """The ``proxies`` mapping of the requests library: one proxy URL per URL scheme."""

    http: str
    https: str


class ProxyConfig(ABC):
    """Base class of the proxy configurations: anything that produces a
    :class:`RequestsProxyConfigDict`."""

    @abstractmethod
    def to_requests_dict(self) -> RequestsProxyConfigDict:
        """The proxies, as the requests library expects them."""

    @property
    def prevent_keeping_connections_alive(self) -> bool:
        """Whether every request should use a new connection (useful with rotating proxies)."""
        return False

    @property
    def retries_when_blocked(self) -> int:
        """How often a request that YouTube blocked is retried (useful with rotating proxies)."""
        return 0


class GenericProxyConfig(ProxyConfig):
    """Any HTTP proxy; when only one of the two URLs is given, it is used for both schemes."""

    def __init__(self, http_url: str | None = None, https_url: str | None = None) -> None:
        if not http_url and not https_url:
            raise InvalidProxyConfig(
                "GenericProxyConfig requires you to define at least one of the two: http or https"
            )
        self.http_url = http_url
        self.https_url = https_url

    def to_requests_dict(self) -> RequestsProxyConfigDict:
        return {
            "http": self.http_url or self.https_url or "",
            "https": self.https_url or self.http_url or "",
        }


class WebshareProxyConfig(GenericProxyConfig):
    """Webshare's rotating residential proxies.

    Args:
        proxy_username: the "Proxy Username" of your Webshare proxy settings.
        proxy_password: the "Proxy Password" of your Webshare proxy settings.
        filter_ip_locations: country codes that limit the pool of IP addresses.
        retries_when_blocked: how often a blocked request is retried with a new IP address.
        domain_name: the proxy host.
        proxy_port: the proxy port.
    """

    DEFAULT_DOMAIN_NAME = "p.webshare.io"
    DEFAULT_PORT = 80

    def __init__(  # noqa: PLR0917
        self,
        proxy_username: str,
        proxy_password: str,
        filter_ip_locations: list[str] | None = None,
        retries_when_blocked: int = 10,
        domain_name: str = DEFAULT_DOMAIN_NAME,
        proxy_port: int = DEFAULT_PORT,
    ) -> None:
        self.proxy_username = proxy_username
        self.proxy_password = proxy_password
        self.domain_name = domain_name
        self.proxy_port = proxy_port
        self._filter_ip_locations = filter_ip_locations or []
        self._retries_when_blocked = retries_when_blocked

    @property
    def url(self) -> str:
        location_codes = "".join(
            f"-{location_code.upper()}" for location_code in self._filter_ip_locations
        )
        username = self.proxy_username
        suffix = "-rotate"
        if username.endswith(suffix):
            username = username[: -len(suffix)]
        return (
            f"http://{username}{location_codes}{suffix}:{self.proxy_password}"
            f"@{self.domain_name}:{self.proxy_port}/"
        )

    @property
    def http_url(self) -> str:  # type: ignore[override]
        return self.url

    @property
    def https_url(self) -> str:  # type: ignore[override]
        return self.url

    @property
    def prevent_keeping_connections_alive(self) -> bool:
        return True

    @property
    def retries_when_blocked(self) -> int:
        return self._retries_when_blocked
