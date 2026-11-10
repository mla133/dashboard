"""T03: authentication and token cache (FR-005..011, NFR-001)."""
from __future__ import annotations

import threading
import time

import pytest

from lcars_dash import teams_ops
from . import teams_fakes as fk


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def signed_out(fake_msal, write_config):
    write_config()
    fake_msal.signed_out()
    return fake_msal


def test_silent_token_avoids_device_flow(fake_msal, write_config):
    write_config()
    assert teams_ops._token() == "tok-silent"
    assert fake_msal.flow_calls == []
    assert fake_msal.silent_calls[0]["scopes"] == ["Chat.Read", "User.Read"]
    assert teams_ops.auth_state()["state"] == "signed_in"


def test_device_flow_scopes_code_and_url_available_while_blocked(signed_out):
    with pytest.raises(teams_ops.TeamsSignInRequired) as exc:
        teams_ops._token()
    e = exc.value
    assert (e.user_code, e.verification_uri) == ("ABCD1234", "https://microsoft.com/devicelogin")
    assert "ABCD1234" in e.message
    assert signed_out.flow_calls[0]["scopes"] == ["Chat.Read", "User.Read"]
    st = teams_ops.auth_state()
    assert st["state"] == "pending" and st["user_code"] == "ABCD1234" and st["verification_uri"].endswith("devicelogin")
    signed_out.complete_event.set()


def test_second_call_while_pending_reuses_flow(signed_out):
    for _ in range(2):
        with pytest.raises(teams_ops.TeamsSignInRequired) as exc:
            teams_ops._token()
        assert exc.value.user_code == "ABCD1234"
    assert len(signed_out.flow_calls) == 1
    signed_out.complete_event.set()


def test_concurrent_threads_start_one_flow(signed_out):
    codes, barrier = [], threading.Barrier(2)

    def worker():
        barrier.wait()
        try:
            teams_ops._token()
        except teams_ops.TeamsSignInRequired as e:
            codes.append(e.user_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert len(signed_out.flow_calls) == 1
    assert codes == ["ABCD1234", "ABCD1234"]
    signed_out.complete_event.set()


def test_completion_success_sets_signed_in_and_token_available(signed_out):
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops._token()
    signed_out.complete_event.set()
    assert wait_for(lambda: teams_ops.auth_state()["state"] == "signed_in")
    assert teams_ops._token() == "tok-device"
    assert len(signed_out.flow_calls) == 1


def test_expiry_marks_failed_with_retry_hint(signed_out):
    signed_out.complete_result = {"error": "expired_token", "error_description": "AADSTS70019: expired\nTrace"}
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops._token()
    signed_out.complete_event.set()
    assert wait_for(lambda: teams_ops.auth_state()["state"] == "failed")
    assert teams_ops.auth_state()["error"] == "code expired"
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._token()
    assert not isinstance(exc.value, teams_ops.TeamsSignInRequired)
    assert "Teams sign-in failed" in str(exc.value) and "press r to retry" in str(exc.value)
    assert len(signed_out.flow_calls) == 1  # failed state does not start a new flow by itself


@pytest.mark.parametrize("res,reason", [
    ({"error": "authorization_declined"}, "sign-in declined"),
    ({"error": "x", "error_description": "first line\nsecond"}, "first line"),
    ({"error": "weird"}, "weird"),
    ({}, "unknown error"),
])
def test_flow_reason(res, reason):
    assert teams_ops._flow_reason(res) == reason


def test_flow_thread_exception_becomes_failed(signed_out):
    signed_out.complete_result = RuntimeError("network down")
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops._token()
    signed_out.complete_event.set()
    assert wait_for(lambda: teams_ops.auth_state()["state"] == "failed")
    assert "network down" in teams_ops.auth_state()["error"]


def test_retry_sign_in_allows_new_flow(signed_out):
    signed_out.complete_result = {"error": "authorization_declined"}
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops._token()
    signed_out.complete_event.set()
    assert wait_for(lambda: teams_ops.auth_state()["state"] == "failed")
    teams_ops.retry_sign_in()
    assert teams_ops.auth_state()["state"] == "idle"
    signed_out.complete_event.clear()
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops._token()
    assert len(signed_out.flow_calls) == 2
    signed_out.complete_event.set()


def test_retry_sign_in_keeps_pending_flow(signed_out):
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops._token()
    teams_ops.retry_sign_in()
    assert teams_ops.auth_state()["state"] == "pending"
    signed_out.complete_event.set()


def test_flow_start_error_is_failed(signed_out):
    signed_out.flow = {"error": "invalid_client", "error_description": "AADSTS7000218: public client not enabled\nx"}
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._token()
    assert not isinstance(exc.value, teams_ops.TeamsSignInRequired)
    assert "public client not enabled" in str(exc.value) and "press r to retry" in str(exc.value)
    assert teams_ops.auth_state()["state"] == "failed"


def test_expired_pending_flow_starts_new_one(signed_out):
    signed_out.flow = fk.device_flow(expires_in=-5)
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops._token()
    signed_out.flow = fk.device_flow(user_code="NEWCODE9")
    with pytest.raises(teams_ops.TeamsSignInRequired) as exc:
        teams_ops._token()
    assert exc.value.user_code == "NEWCODE9" and len(signed_out.flow_calls) == 2
    signed_out.complete_event.set()


def test_auth_state_never_blocks_while_init_lock_held(signed_out):
    with teams_ops._init_lock:
        assert teams_ops.auth_state()["state"] == "idle"
        teams_ops.retry_sign_in()


def test_app_not_cached_on_construction_failure(fake_msal, write_config):
    write_config()
    fake_msal.construct_error = OSError("offline")
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._token()
    assert "Cannot reach Microsoft sign-in" in str(exc.value)
    fake_msal.construct_error = None
    assert teams_ops._token() == "tok-silent"


def test_bad_authority_is_not_configured(fake_msal, write_config):
    write_config()
    fake_msal.construct_error = ValueError("bad authority")
    with pytest.raises(teams_ops.TeamsNotConfigured) as exc:
        teams_ops._token()
    assert "tenant_id rejected" in str(exc.value)


def test_config_change_rebuilds_app_and_resets_state(fake_msal, write_config):
    write_config()
    teams_ops._token()
    write_config(tenant_id="other.onmicrosoft.com")
    teams_ops._token()
    assert len(fake_msal.apps) == 2 and fake_msal.apps[1].authority.endswith("/other.onmicrosoft.com")


# ---- token cache ---------------------------------------------------------------------------------

def test_no_extensions_uses_memory_cache_and_notice(fake_msal, write_config):
    write_config()
    teams_ops._token()
    assert not teams_ops.TOKEN_FILE.exists()
    assert isinstance(fake_msal.apps[0].token_cache, fk.FakeTokenCache)
    notice = teams_ops.auth_state()["cache_notice"]
    assert notice.startswith("Teams token cache unavailable") and "msal-extensions not installed" in notice


def test_encrypted_persistence_used_with_token_file(fake_extensions, fake_msal, write_config):
    write_config()
    teams_ops._token()
    assert fake_extensions.built == [str(teams_ops.TOKEN_FILE)]
    assert isinstance(fake_msal.apps[0].token_cache, fake_extensions.PersistedTokenCache)
    assert teams_ops.auth_state()["cache_notice"] == ""
    assert teams_ops.DIR.is_dir()
    assert not teams_ops.TOKEN_FILE.exists()  # fake persistence writes nothing; app never writes plaintext itself


def test_persistence_not_found_is_ok(fake_msal, write_config, monkeypatch):
    import sys
    ext = fk.FakeExtensions(raise_not_found=True)
    monkeypatch.setitem(sys.modules, "msal_extensions", ext)
    write_config()
    teams_ops._token()
    assert teams_ops.auth_state()["cache_notice"] == ""


def test_persistence_failure_falls_back_to_memory(fake_msal, write_config, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "msal_extensions", fk.FakeExtensions(build_error=OSError("dpapi unavailable")))
    write_config()
    teams_ops._token()
    notice = teams_ops.auth_state()["cache_notice"]
    assert "OSError: dpapi unavailable" in notice
    assert isinstance(fake_msal.apps[0].token_cache, fk.FakeTokenCache)
    assert not teams_ops.TOKEN_FILE.exists()


def test_token_never_in_exception_or_state(signed_out):
    with pytest.raises(teams_ops.TeamsSignInRequired) as exc:
        teams_ops._token()
    assert "tok-" not in str(exc.value) and "tok-" not in repr(teams_ops.auth_state())
    signed_out.complete_event.set()
