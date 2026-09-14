from api.serve import DUALSTACK_HOSTS, listen_hosts, listen_port, server_config


def test_default_bind_is_ipv4_and_ipv6_on_railway_port():
    assert listen_hosts({}) == ["0.0.0.0", "::"]
    assert listen_port({}) == 8000
    assert listen_port({"PORT": "8080"}) == 8080


def test_bind_override_stays_single_process_host_list():
    assert listen_hosts({"OPTIONBEACON_API_BIND": "127.0.0.1"}) == ["127.0.0.1"]
    assert listen_hosts({"OPTIONBEACON_API_BIND": "0.0.0.0, ::"}) == ["0.0.0.0", "::"]


def test_uvicorn_config_is_single_worker_and_bind_helper_keeps_v6only():
    config = server_config(hosts=list(DUALSTACK_HOSTS), port=9)
    assert config.port == 9
    assert config.workers == 1
    assert config.uds is None
    assert config.fd is None


def test_bind_sockets_listens_on_ipv4_and_skips_unavailable_families():
    import socket

    from api.serve import bind_sockets

    sockets = bind_sockets(["127.0.0.1"], 0)
    try:
        assert len(sockets) == 1
        assert sockets[0].getsockname()[1] > 0
        assert sockets[0].family == socket.AF_INET
    finally:
        for sock in sockets:
            sock.close()


def test_ipv6_bind_sets_v6only_when_the_stack_is_available():
    import socket

    from api.serve import bind_sockets

    try:
        sockets = bind_sockets(["::1"], 0)
    except RuntimeError:
        return
    try:
        assert sockets[0].family == socket.AF_INET6
        assert sockets[0].getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1
    finally:
        for sock in sockets:
            sock.close()
