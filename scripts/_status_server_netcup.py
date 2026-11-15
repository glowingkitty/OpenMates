"""netcup Server Control Panel (SCP) REST API client for the status server.

Authentication is netcup's OpenID Connect device flow (realm ``scp``, client
``scp``, scope ``offline_access openid``): the operator approves one login in
the browser and we keep only the long-lived refresh token in Vault. Each run
exchanges it for a short-lived access token.

Only the calls the status server needs: list servers, read IPs, upload an SSH
key, install an image with that key, and wait for netcup tasks.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

SCP = "https://www.servercontrolpanel.de"
DEVICE_URL = f"{SCP}/realms/scp/protocol/openid-connect/auth/device"
TOKEN_URL = f"{SCP}/realms/scp/protocol/openid-connect/token"
API = f"{SCP}/scp-core/api/v1"
CLIENT_ID = "scp"
SCOPE = "offline_access openid"
TIMEOUT_S = 30


class NetcupError(RuntimeError):
    """A netcup API call failed; the message carries no token."""


def _form(url: str, fields: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = _json_or_empty(exc.read())
        raise NetcupError(f"{url.rsplit('/', 1)[-1]}: HTTP {exc.code} {body.get('error', '')}".strip()) from exc


def _json_or_empty(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class DeviceLogin:
    device_code: str
    user_code: str
    verification_url: str
    interval_s: int
    expires_in_s: int


def start_device_login() -> DeviceLogin:
    """Begin the browser login; show ``verification_url`` to the operator."""
    data = _form(DEVICE_URL, {"client_id": CLIENT_ID, "scope": SCOPE})
    return DeviceLogin(data["device_code"], data["user_code"],
                       data.get("verification_uri_complete") or data["verification_uri"],
                       int(data.get("interval", 5)), int(data.get("expires_in", 600)))


def wait_for_refresh_token(login: DeviceLogin, sleep: Callable[[float], None] = time.sleep) -> str:
    """Poll until the operator approved the login; return the refresh token."""
    deadline = time.monotonic() + login.expires_in_s
    interval = login.interval_s
    while time.monotonic() < deadline:
        sleep(interval)
        try:
            data = _form(TOKEN_URL, {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                     "device_code": login.device_code, "client_id": CLIENT_ID})
        except NetcupError as exc:
            if "authorization_pending" in str(exc):
                continue
            if "slow_down" in str(exc):
                interval += 5
                continue
            raise
        token = data.get("refresh_token")
        if not token:
            raise NetcupError("login approved but no refresh token was issued")
        return str(token)
    raise NetcupError("login was not approved in time")


def access_token(refresh_token: str) -> str:
    data = _form(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": refresh_token,
                             "client_id": CLIENT_ID})
    return str(data["access_token"])


def user_id_from_token(token: str) -> int:
    """The SCP user id (not the customer number) from the access token claims."""
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    for name in ("id", "userId", "user_id"):
        if str(claims.get(name, "")).isdigit():
            return int(claims[name])
    raise NetcupError(f"no SCP user id in token claims ({', '.join(sorted(claims))})")


class Client:
    """Authenticated SCP API calls."""

    def __init__(self, token: str) -> None:
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None) -> Any:
        request = urllib.request.Request(
            f"{API}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = _json_or_empty(exc.read()).get("message", "")
            raise NetcupError(f"{method} {path}: HTTP {exc.code} {detail}".strip()) from exc
        return json.loads(raw) if raw else None

    def servers(self) -> list[dict]:
        return list(self.call("GET", "/servers") or [])

    def ipv4_addresses(self, server_id: int) -> list[str]:
        return [ip for interface in self.call("GET", f"/servers/{server_id}/interfaces") or []
                for ip in interface.get("ipv4Addresses") or []]

    def ensure_ssh_key(self, user_id: int, name: str, public_key: str) -> int:
        for key in self.call("GET", f"/users/{user_id}/ssh-keys") or []:
            if key.get("key", "").split()[:2] == public_key.split()[:2]:
                return int(key["id"])
        created = self.call("POST", f"/users/{user_id}/ssh-keys", {"name": name, "key": public_key})
        return int(created["id"])

    def debian_flavour(self, server_id: int, release: str = "13") -> dict:
        flavours = self.call("GET", f"/servers/{server_id}/imageflavours") or []
        matches = [f for f in flavours if f"Debian {release}" in f.get("name", "") or
                   f"debian-{release}" in f.get("alias", "")]
        if not matches:
            raise NetcupError(f"no Debian {release} image offered ({len(flavours)} flavours)")
        minimal = [f for f in matches if "minimal" in (f.get("name", "") + f.get("alias", "")).lower()]
        return (minimal or matches)[0]

    def install_image(self, server_id: int, flavour_id: int, ssh_key_id: int, hostname: str) -> str:
        task = self.call("POST", f"/servers/{server_id}/image", {
            "imageFlavourId": flavour_id, "sshKeyIds": [ssh_key_id], "hostname": hostname,
            "rootPartitionFullDiskSize": True, "emailNotification": False})
        return str(task["uuid"])

    def wait_task(self, uuid: str, timeout_s: int = 1800, sleep: Callable[[float], None] = time.sleep) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            state = (self.call("GET", f"/tasks/{uuid}") or {}).get("state")
            if state == "FINISHED":
                return
            if state in {"ERROR", "CANCELED", "ROLLBACK"}:
                raise NetcupError(f"netcup task ended in state {state}")
            sleep(15)
        raise NetcupError("netcup task did not finish in time")
