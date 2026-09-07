"""Bounded image downloads pinned to public addresses of allowlisted hosts."""

import ipaddress
import socket
from urllib.parse import urlparse, urlunparse

import urllib3
from django.core.exceptions import ValidationError
from requests.certs import where as default_ca_bundle_path

from uploads.utils import validate_image_source_url


def download_image_source(url: str, *, max_size: int, timeout: float) -> tuple[bytes, str]:
    validate_image_source_url(url)
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValidationError("Image source hostname could not be resolved.") from exc
    if not addresses:
        raise ValidationError("Image source hostname has no addresses.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise ValidationError("Image source hostname resolves to a non-public address.")

    # Pin the connection, not just validation: a second hostname lookup could rebind.
    address = sorted(addresses)[0]
    request_timeout = urllib3.Timeout(connect=timeout, read=timeout)
    if parsed.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(
            address,
            port=port,
            timeout=request_timeout,
            retries=False,
            cert_reqs="CERT_REQUIRED",
            ca_certs=default_ca_bundle_path(),
            assert_hostname=parsed.hostname,
            server_hostname=parsed.hostname,
        )
    else:
        pool = urllib3.HTTPConnectionPool(address, port=port, timeout=request_timeout, retries=False)

    response = None
    try:
        response = pool.urlopen(
            "GET",
            urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, "")),
            headers={"Host": parsed.netloc, "Accept-Encoding": "identity"},
            preload_content=False,
            decode_content=False,
            redirect=False,
            retries=False,
        )
        if response.status != 200:
            raise ValueError("Image source did not return HTTP 200")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("Image source returned an unsupported content encoding")
        content_length = response.headers.get("Content-Length")
        if content_length is not None and (not content_length.isdigit() or int(content_length) > max_size):
            raise ValueError("Image source has an invalid or excessive content length")
        content = response.read(max_size + 1, decode_content=False)
        if len(content) > max_size:
            raise ValueError("Photo exceeds max file size")
        return content, response.headers.get("Content-Type", "image/jpeg")
    finally:
        if response is not None:
            response.close()
            response.release_conn()
        pool.close()
