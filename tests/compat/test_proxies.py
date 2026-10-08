"""youtube-transcript-api 1.2.4's proxy tests, run against utmax.compat.proxies."""

from __future__ import annotations

import pytest

from utmax.compat.proxies import (
    GenericProxyConfig,
    InvalidProxyConfig,
    ProxyConfig,
    WebshareProxyConfig,
)


class TestGenericProxyConfig:
    def test_to_requests_dict(self) -> None:
        proxy_config = GenericProxyConfig(
            http_url="http://myproxy.com",
            https_url="https://myproxy.com",
        )

        assert proxy_config.to_requests_dict() == {
            "http": "http://myproxy.com",
            "https": "https://myproxy.com",
        }

    def test_to_requests_dict__only_http(self) -> None:
        proxy_config = GenericProxyConfig(http_url="http://myproxy.com")

        assert proxy_config.to_requests_dict() == {
            "http": "http://myproxy.com",
            "https": "http://myproxy.com",
        }

    def test_to_requests_dict__only_https(self) -> None:
        proxy_config = GenericProxyConfig(https_url="https://myproxy.com")

        assert proxy_config.to_requests_dict() == {
            "http": "https://myproxy.com",
            "https": "https://myproxy.com",
        }

    def test__invalid_config(self) -> None:
        with pytest.raises(InvalidProxyConfig):
            GenericProxyConfig()

    def test_defaults_keep_connections_and_never_retry(self) -> None:
        proxy_config = GenericProxyConfig(http_url="http://myproxy.com")

        assert proxy_config.prevent_keeping_connections_alive is False
        assert proxy_config.retries_when_blocked == 0


class TestWebshareProxyConfig:
    def test_to_requests_dict(self) -> None:
        proxy_config = WebshareProxyConfig(proxy_username="user", proxy_password="password")

        assert proxy_config.to_requests_dict() == {
            "http": "http://user-rotate:password@p.webshare.io:80/",
            "https": "http://user-rotate:password@p.webshare.io:80/",
        }

    def test_to_requests_dict__with_location_filter(self) -> None:
        proxy_config = WebshareProxyConfig(
            proxy_username="user",
            proxy_password="password",
            filter_ip_locations=["us"],
        )

        assert proxy_config.to_requests_dict() == {
            "http": "http://user-US-rotate:password@p.webshare.io:80/",
            "https": "http://user-US-rotate:password@p.webshare.io:80/",
        }

    def test_to_requests_dict__with_multiple_location_filters(self) -> None:
        proxy_config = WebshareProxyConfig(
            proxy_username="user",
            proxy_password="password",
            filter_ip_locations=["de", "us"],
        )

        assert proxy_config.to_requests_dict() == {
            "http": "http://user-DE-US-rotate:password@p.webshare.io:80/",
            "https": "http://user-DE-US-rotate:password@p.webshare.io:80/",
        }

    def test_to_requests_dict__with_rotate_suffix_in_username(self) -> None:
        proxy_config = WebshareProxyConfig(proxy_username="user-rotate", proxy_password="password")

        assert proxy_config.to_requests_dict() == {
            "http": "http://user-rotate:password@p.webshare.io:80/",
            "https": "http://user-rotate:password@p.webshare.io:80/",
        }

    def test_rotating_settings_and_custom_endpoint(self) -> None:
        proxy_config = WebshareProxyConfig(
            "user", "password", retries_when_blocked=3, domain_name="proxy.test", proxy_port=8080
        )

        assert proxy_config.url == "http://user-rotate:password@proxy.test:8080/"
        assert proxy_config.http_url == proxy_config.https_url == proxy_config.url
        assert proxy_config.prevent_keeping_connections_alive is True
        assert proxy_config.retries_when_blocked == 3
        assert isinstance(proxy_config, ProxyConfig)
