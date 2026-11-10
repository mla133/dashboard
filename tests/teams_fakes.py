"""Fakes and JSON builders for the Teams tests: no real msal, msal_extensions or network is ever used."""
from __future__ import annotations

import threading
import time

GOOD_CLIENT_ID = "11111111-2222-3333-4444-555555555555"
GOOD_TENANT_ID = "99999999-8888-7777-6666-555555555555"
ME_ID = "me-id-0001"


# --------------------------------------------------------------------------- MSAL fakes

class FakeApp:
    """Stands in for msal.PublicClientApplication; behaviour is steered through the owning FakeMsalModule."""

    def __init__(self, mod, client_id, authority, token_cache):
        self.mod = mod
        self.client_id, self.authority, self.token_cache = client_id, authority, token_cache

    def get_accounts(self):
        return list(self.mod.accounts)

    def acquire_token_silent(self, scopes, account=None, force_refresh=False):
        self.mod.silent_calls.append({"scopes": list(scopes), "account": account, "force_refresh": force_refresh})
        results = self.mod.silent_results
        return results.pop(0) if len(results) > 1 else (results[0] if results else None)

    def initiate_device_flow(self, scopes=None):
        self.mod.flow_calls.append({"scopes": list(scopes or [])})
        time.sleep(0.02)  # widen the race window for the concurrency test
        return self.mod.flow

    def acquire_token_by_device_flow(self, flow):
        self.mod.complete_started.set()
        self.mod.complete_event.wait(5)
        res = self.mod.complete_result
        if isinstance(res, Exception):
            raise res
        if "access_token" in res:
            self.mod.accounts.append({"home_account_id": "acct-1"})
            self.mod.silent_results[:] = [{"access_token": res["access_token"]}]
        return res

    def remove_account(self, account):
        self.mod.removed.append(account)
        if account in self.mod.accounts:
            self.mod.accounts.remove(account)


class FakeTokenCache:
    pass


class FakeMsalModule:
    """Drop-in for the `msal` module. Defaults: one cached account and a valid silent token."""

    def __init__(self):
        self.apps: list[FakeApp] = []
        self.accounts: list[dict] = [{"home_account_id": "acct-1"}]
        self.silent_results: list = [{"access_token": "tok-silent"}]
        self.silent_calls: list[dict] = []
        self.flow_calls: list[dict] = []
        self.removed: list = []
        self.flow = device_flow()
        self.complete_event = threading.Event()  # device flow completion is blocked until set()
        self.complete_started = threading.Event()
        self.complete_result: dict | Exception = {"access_token": "tok-device"}
        self.construct_error: Exception | None = None
        self.TokenCache = FakeTokenCache

    def PublicClientApplication(self, client_id, authority=None, token_cache=None):  # noqa: N802 (msal API name)
        if self.construct_error:
            raise self.construct_error
        app = FakeApp(self, client_id, authority, token_cache)
        self.apps.append(app)
        return app

    def signed_out(self):
        """No cached account: the next token request must use the device flow."""
        self.accounts.clear()
        self.silent_results[:] = [None]
        return self


def device_flow(user_code="ABCD1234", uri="https://microsoft.com/devicelogin", expires_in=900):
    return {"user_code": user_code, "verification_uri": uri, "expires_in": expires_in,
            "expires_at": time.time() + expires_in,
            "message": f"To sign in, use a web browser to open {uri} and enter the code {user_code}"}


class FakePersistence:
    def __init__(self, path, raise_not_found=False):
        self.path, self.raise_not_found = path, raise_not_found

    def load(self):
        if self.raise_not_found:
            raise type("PersistenceNotFound", (Exception,), {})("no file yet")
        return ""


class FakeExtensions:
    """Drop-in for `msal_extensions`: records the encrypted-persistence path; PersistedTokenCache is a marker class."""

    def __init__(self, raise_not_found=False, build_error: Exception | None = None):
        self.built: list[str] = []
        self.raise_not_found, self.build_error = raise_not_found, build_error

        class PersistedTokenCache:
            def __init__(self, persistence):
                self.persistence = persistence

        self.PersistedTokenCache = PersistedTokenCache

    def build_encrypted_persistence(self, path):
        if self.build_error:
            raise self.build_error
        self.built.append(path)
        return FakePersistence(path, self.raise_not_found)


# --------------------------------------------------------------------------- HTTP fakes

_INVALID = object()


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, reason=""):
        self.status_code, self._json, self.headers, self.reason = status_code, json_data, headers or {}, reason

    def json(self):
        if self._json is _INVALID:
            raise ValueError("no JSON")
        return self._json


def invalid_json_response(status=200):
    return FakeResponse(status, _INVALID)


class FakeGraph:
    """Routes requests.get by Graph path (or full URL). Each route holds a queue of responses/exceptions;
    the last one repeats. Every call is recorded."""

    GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.routes: dict[str, list] = {}
        self.calls: list[dict] = []
        self.other_verb_calls: list[str] = []

    def add(self, key: str, *responses):
        self.routes[key] = [FakeResponse(200, r) if isinstance(r, dict) else r for r in responses]
        return self

    def get(self, url, headers=None, params=None, timeout=None, **kw):
        self.calls.append({"method": "GET", "url": url, "params": params, "headers": headers, "timeout": timeout})
        path = url[len(self.GRAPH):] if url.startswith(self.GRAPH) else url
        queue = self.routes.get(path) or self.routes.get(url)
        if not queue:
            return FakeResponse(404, {"error": {"message": f"no route for {path}"}}, reason="Not Found")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def paths(self, prefix=""):
        return [c["url"][len(self.GRAPH):] for c in self.calls if c["url"][len(self.GRAPH):].startswith(prefix)]


# --------------------------------------------------------------------------- Graph JSON builders

def me_json(uid=ME_ID, name="Me Myself"):
    return {"id": uid, "displayName": name}


def member(name, uid):
    return {"displayName": name, "userId": uid}


def preview(created="2026-11-10T14:30:00Z", text="hello", sender="Alice", html=False, deleted=False, msg_type="message"):
    return {"createdDateTime": created, "isDeleted": deleted, "messageType": msg_type,
            "body": {"contentType": "html" if html else "text", "content": text},
            "from": {"user": {"id": "u-" + sender, "displayName": sender}}}


def chat_json(cid="19:abc@thread.v2", chat_type="oneOnOne", topic=None, members=None, last=None, last_read=None):
    d = {"id": cid, "chatType": chat_type, "topic": topic, "webUrl": f"https://teams.example/{cid}",
         "viewpoint": {"lastMessageReadDateTime": last_read}}
    if members is not None:
        d["members"] = members
    if last is not None:
        d["lastMessagePreview"] = last
    return d


def message_json(mid="m1", created="2026-11-10T14:00:00Z", text="hi", sender="Alice", html=False, mentions=None,
                 deleted=False, msg_type="message", attachments=None):
    return {"id": mid, "messageType": msg_type, "createdDateTime": created,
            "deletedDateTime": "2026-11-10T15:00:00Z" if deleted else None,
            "body": {"contentType": "html" if html else "text", "content": text},
            "from": {"user": {"id": "u-" + sender, "displayName": sender}} if msg_type == "message" else None,
            "mentions": mentions or [], "attachments": attachments or []}


def mention(uid):
    return {"id": 0, "mentionText": "x", "mentioned": {"user": {"id": uid, "displayName": "x"}}}


def page(items, next_link=None):
    d = {"value": items}
    if next_link:
        d["@odata.nextLink"] = next_link
    return d
