"""Public-web transport: pin validated DNS answers and bound decoded responses."""

import asyncio
import ipaddress
import json
import socket
import time

import httpx

FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")


def _public(ip):
    return ip.is_global and not ip.is_multicast and not (
        ip.version == 6
        and (
            ip.ipv4_mapped
            or ip.sixtofour
            or ip.teredo
            or ip in ipaddress.ip_network("64:ff9b::/96")
        )
    )


class LimitedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        deadline, size = time.monotonic() + 30, 0
        iterator = self.stream.__aiter__()
        while True:
            try:
                chunk = await asyncio.wait_for(
                    iterator.__anext__(), max(0, deadline - time.monotonic())
                )
            except StopAsyncIteration:
                return
            size += len(chunk)
            if size > 8 * 1024 * 1024:
                raise httpx.RequestError("Preview response exceeds 8 MiB")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class PublicTransport(httpx.AsyncBaseTransport):
    def __init__(self, proxy=None):
        # Pinned IPs can be shared by different TLS hosts; do not reuse their sockets.
        self.inner = httpx.AsyncHTTPTransport(
            proxy=proxy, limits=httpx.Limits(max_keepalive_connections=0)
        )
        self._dns_cache = {}

    async def _doh_query(self, host, resolver, bootstrap, path, record_type):
        # Bootstrap by a fixed public IP so the resolver itself cannot get a Fake-IP.
        request = httpx.Request(
            "GET",
            httpx.URL(f"https://{bootstrap}{path}", params={
                "name": host, "type": record_type, "edns_client_subnet": "0.0.0.0/0"
            }),
            headers={"Host": resolver, "Accept": "application/dns-json",
                     "Accept-Encoding": "identity"},
            extensions={"sni_hostname": resolver,
                        "timeout": {"connect": 3, "read": 3, "write": 3, "pool": 3}},
        )
        response = await self.inner.handle_async_request(request)
        try:
            if response.status_code != 200 or response.headers.get(
                "content-encoding", "identity"
            ).lower() != "identity":
                raise ValueError("Invalid DNS response")
            body = bytearray()
            async for chunk in response.stream:
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError("DNS response exceeds 64 KiB")
            data = json.loads(body)
            if not isinstance(data, dict) or data.get("Status") != 0 or data.get("TC"):
                raise ValueError("DNS lookup failed")
            records = data.get("Answer", [])
            addresses = [ipaddress.ip_address(r["data"]) for r in records
                         if r["type"] in (1, 28)]
            ttl = min((int(r.get("TTL", 0)) for r in records), default=0)
            return addresses, max(0, min(ttl, 60))
        finally:
            await response.aclose()

    async def _real_addresses(self, host):
        for resolver, bootstrap, path in (
            ("cloudflare-dns.com", "1.1.1.1", "/dns-query"),
            ("dns.google", "8.8.8.8", "/resolve"),
        ):
            try:
                addresses, ttl = await asyncio.wait_for(
                    self._doh_query(host, resolver, bootstrap, path, "A"), 3
                )
                if not addresses:
                    addresses, ttl = await asyncio.wait_for(
                        self._doh_query(host, resolver, bootstrap, path, "AAAA"), 3
                    )
            except (TimeoutError, httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
                continue
            # A private answer is a denial, not a reason to try another resolver.
            if not addresses or not all(_public(ip) for ip in addresses):
                raise ValueError("Non-public DNS answer")
            if len(self._dns_cache) >= 128:
                self._dns_cache.pop(next(iter(self._dns_cache)))
            self._dns_cache[host] = (time.monotonic() + ttl, addresses)
            return addresses
        raise ValueError("Public DNS lookup failed; check proxy connectivity")

    async def _addresses(self, host, port):
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            addresses = [literal]
        else:
            cached = self._dns_cache.get(host)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            answers = await asyncio.wait_for(
                asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM),
                timeout=5,
            )
            addresses = [ipaddress.ip_address(item[4][0]) for item in answers]
            if addresses and any(ip in FAKE_IP_RANGE for ip in addresses):
                if not all(_public(ip) or ip in FAKE_IP_RANGE for ip in addresses):
                    raise ValueError("Non-public address mixed with Fake-IP")
                return await asyncio.wait_for(self._real_addresses(host), 8)
        if not addresses or not all(_public(ip) for ip in addresses):
            raise ValueError("Non-public address")
        return addresses

    async def handle_async_request(self, request):
        url = request.url
        if url.scheme not in ("http", "https") or url.userinfo:
            raise httpx.RequestError(
                "Only public HTTP(S) URLs are allowed", request=request
            )
        try:
            addresses = await self._addresses(
                url.raw_host.decode("ascii"),
                url.port or (443 if url.scheme == "https" else 80),
            )
        except (TimeoutError, OSError, ValueError) as exc:
            raise httpx.RequestError(
                "Preview destination is unavailable or non-public", request=request
            ) from exc
        # Pin the socket destination; a second DNS lookup must not undo validation.
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=str(addresses[0])),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": url.raw_host.decode("ascii")},
        )
        # Decline compressed bodies rather than allocating a decompression bomb.
        pinned.headers["Accept-Encoding"] = "identity"
        response = await self.inner.handle_async_request(pinned)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise httpx.RequestError(
                "Compressed preview response is not accepted", request=request
            )
        response.stream = LimitedStream(response.stream)
        return response

    async def aclose(self):
        await self.inner.aclose()


class PreviewClient(httpx.AsyncClient):
    async def send(self, request, *, stream=False, **kwargs):
        response = await super().send(request, stream=True, **kwargs)
        if stream:
            return response
        try:
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > 8 * 1024 * 1024:
                    raise httpx.RequestError("Preview response exceeds 8 MiB", request=request)
            headers = response.headers.copy()
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            return httpx.Response(
                response.status_code, headers=headers, content=bytes(data),
                request=response.request, history=response.history, extensions=response.extensions,
            )
        finally:
            await response.aclose()
