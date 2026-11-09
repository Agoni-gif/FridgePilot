from __future__ import annotations

from fastapi import Request


def client_key(request: Request) -> str:
    """限流用的客户端标识：优先 X-Forwarded-For 首段，否则直连 IP。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
