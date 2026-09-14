"""One-process dual-stack HTTP server for Railway.

Uvicorn's CLI ``--host`` accepts a single address. Binding only ``0.0.0.0``
misses legacy IPv6-only private DNS; binding only ``::`` misses IPv4
healthchecks. This entrypoint opens one IPv4 socket and one IPv6 socket
(V6ONLY) on the same PORT and hands both to a single Uvicorn process.
"""
from __future__ import annotations

import logging
import os
import socket

import uvicorn

from api.main import app

logger = logging.getLogger("optionbeacon.api")

DUALSTACK_HOSTS = ("0.0.0.0", "::")


def listen_hosts(environ=None) -> list[str]:
    environment = os.environ if environ is None else environ
    raw = str(environment.get("OPTIONBEACON_API_BIND") or "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return list(DUALSTACK_HOSTS)


def listen_port(environ=None) -> int:
    environment = os.environ if environ is None else environ
    return int(environment.get("PORT") or "8000")


def _family(host: str) -> int:
    return socket.AF_INET6 if ":" in host else socket.AF_INET


def bind_sockets(hosts: list[str], port: int, backlog: int = 2048) -> list[socket.socket]:
    """Bind each host independently so IPv4 healthchecks and IPv6 DNS can coexist."""
    sockets: list[socket.socket] = []
    errors: list[str] = []
    for host in hosts:
        sock = socket.socket(_family(host), socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if sock.family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        try:
            sock.bind((host, port))
            sock.listen(backlog)
            sock.set_inheritable(True)
        except OSError as exc:
            sock.close()
            errors.append(f"{host}:{port} ({exc})")
            logger.warning("api.listen.skipped host=%s port=%s error=%s", host, port, exc)
            continue
        sockets.append(sock)
        logger.info("api.listen.bound host=%s port=%s", host, port)
    if not sockets:
        raise RuntimeError("FastAPI could not bind any address: " + "; ".join(errors))
    return sockets


def server_config(*, application=app, hosts=None, port=None):
    bind_hosts = list(DUALSTACK_HOSTS if hosts is None else hosts)
    return uvicorn.Config(application, host=bind_hosts[0], port=8000 if port is None else port)


def main() -> None:
    hosts = listen_hosts()
    port = listen_port()
    config = server_config(hosts=hosts, port=port)
    sockets = bind_sockets(hosts, port)
    uvicorn.Server(config).run(sockets=sockets)


if __name__ == "__main__":
    main()
