import urllib.parse
import ipaddress

ALLOWED_HOSTS = {
    "www.youtube.com", "youtube.com", "youtu.be",
    "m.youtube.com", "music.youtube.com",
    "generativelanguage.googleapis.com",
}


def validate_url(url: str) -> bool:
    """Validate URL against whitelist. Raises ValueError for disallowed URLs."""
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError(f"Invalid URL: {url}")
    # Check against whitelist
    if hostname not in ALLOWED_HOSTS:
        raise ValueError(f"URL host not allowed: {hostname}")
    # Reject IP-based URLs (SSRF prevention)
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved:
            raise ValueError(f"Private/internal IP addresses not allowed: {hostname}")
    except ValueError as e:
        if "not allowed" in str(e):
            raise
        pass  # Not an IP, that's fine
    return True
