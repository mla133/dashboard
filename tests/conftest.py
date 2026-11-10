"""Shared fixtures: tests never touch the network, the real home directory or the real mindchuk tool."""
from __future__ import annotations

import json
import socket
import sys
import time
from types import SimpleNamespace

import pytest
import requests

from lcars_dash import config, google_ops, mindchuk_ops, teams_ops, tests_ops

from . import teams_fakes as fk


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(*a, **kw):
        raise RuntimeError("network access in tests")

    real_connect = socket.socket.connect

    def loopback_only(self, address, *a, **kw):
        # asyncio's Windows event loop builds a loopback socketpair; anything else is blocked.
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1"):
            return real_connect(self, address, *a, **kw)
        raise RuntimeError("network access in tests")

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(autouse=True)
def _redirect_paths(monkeypatch, tmp_path):
    home = tmp_path / ".lcars_dash"
    monkeypatch.setattr(teams_ops, "DIR", home)
    monkeypatch.setattr(teams_ops, "CONFIG_FILE", home / "teams_config.json")
    monkeypatch.setattr(teams_ops, "TOKEN_FILE", home / "teams_token.bin")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "lcars_dash.json")
    monkeypatch.setattr(tests_ops, "RESULTS_FILE", tmp_path / "lcars_dash_tests.json")
    monkeypatch.setattr(google_ops, "DIR", home)
    monkeypatch.setattr(google_ops, "SECRET", home / "client_secret.json")
    monkeypatch.setattr(google_ops, "TOKEN", home / "google_token.json")


@pytest.fixture(autouse=True)
def _mindchuk_guard(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("mindchuk called")

    monkeypatch.setattr(mindchuk_ops, "add", boom)
    monkeypatch.setattr(mindchuk_ops, "run", boom)


@pytest.fixture(autouse=True)
def _teams_state():
    # getattr: tolerate the absence of _reset (kept from the T01 scaffold, which predates teams_ops)
    reset = getattr(teams_ops, "_reset", None)
    if reset:
        reset()
    yield
    if reset:
        reset()


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """teams_ops never really sleeps; recorded durations are available to tests."""
    calls: list[float] = []
    monkeypatch.setattr(teams_ops, "time", SimpleNamespace(sleep=calls.append, time=time.time, monotonic=time.monotonic))
    return calls


@pytest.fixture
def fake_msal(monkeypatch):
    mod = fk.FakeMsalModule()
    monkeypatch.setitem(sys.modules, "msal", mod)
    monkeypatch.setitem(sys.modules, "msal_extensions", None)  # default: DPAPI cache unavailable (never touch real one)
    return mod


@pytest.fixture
def fake_extensions(monkeypatch, fake_msal):
    ext = fk.FakeExtensions()
    monkeypatch.setitem(sys.modules, "msal_extensions", ext)
    return ext


@pytest.fixture
def write_config():
    def write(client_id=fk.GOOD_CLIENT_ID, tenant_id=fk.GOOD_TENANT_ID, raw=None):
        path = teams_ops.CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw if raw is not None else json.dumps({"client_id": client_id, "tenant_id": tenant_id}), encoding="utf-8")
        return path
    return write


@pytest.fixture
def graph(monkeypatch):
    g = fk.FakeGraph()

    def forbidden(name):
        def fn(*a, **kw):
            g.other_verb_calls.append(name)
            raise AssertionError(f"requests.{name} used (read-only violation)")
        return fn

    monkeypatch.setattr(requests, "get", g.get)
    for verb in ("post", "put", "patch", "delete", "request", "head", "options"):
        monkeypatch.setattr(requests, verb, forbidden(verb))
    return g


@pytest.fixture
def signed_in(fake_msal, write_config, graph):
    """Config written, MSAL faked with a cached account, /me routed. Returns the graph router."""
    write_config()
    graph.add("/me", fk.me_json())
    return graph
