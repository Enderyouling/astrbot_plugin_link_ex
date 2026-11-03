"""Public-web transport: pin validated DNS answers and bound decoded responses."""

import asyncio
import ipaddress
import socket
import time

import httpx


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

    async def handle_async_request(self, request):
        url = request.url
        if url.scheme not in ("http", "https") or url.userinfo:
            raise httpx.RequestError(
                "Only public HTTP(S) URLs are allowed", request=request
            )
        try:
            answers = await asyncio.wait_for(
                asyncio.to_thread(
                    socket.getaddrinfo,
                    url.host,
                    url.port or (443 if url.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                ),
                timeout=5,
            )
            addresses = [item[4][0] for item in answers]
            ips = [ipaddress.ip_address(ip) for ip in addresses]
            if not ips or any(
                not ip.is_global
                or ip.is_multicast
                or (
                    ip.version == 6
                    and (
                        ip.ipv4_mapped
                        or ip.sixtofour
                        or ip.teredo
                        or ip in ipaddress.ip_network("64:ff9b::/96")
                    )
                )
                for ip in ips
            ):
                raise ValueError("Non-public address")
        except (OSError, ValueError, asyncio.TimeoutError) as exc:
            raise httpx.RequestError(
                "Preview destination is unavailable or non-public", request=request
            ) from exc
        # Pin the socket destination; a second DNS lookup must not undo validation.
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=addresses[0]),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": url.host},
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
                    raise httpx.RequestError(
                        "Preview response exceeds 8 MiB", request=request
                    )
            headers = response.headers.copy()
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            return httpx.Response(
                response.status_code,
                headers=headers,
                content=bytes(data),
                request=response.request,
                history=response.history,
                extensions=response.extensions,
            )
        finally:
            await response.aclose()
