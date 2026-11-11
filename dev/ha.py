"""Helpers for the local development Home Assistant (http://localhost:18124).

    python dev/ha.py onboard     create the dev user and a long-lived token (dev/token.txt)
"""

from __future__ import annotations

import json
import pathlib
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

import websocket  # websocket-client

DEV = pathlib.Path(__file__).resolve().parent
URL = "http://localhost:18124"
CLIENT = URL + "/"


def http(path: str, data: dict | None = None, token: str | None = None, form: bool = False,
         method: str | None = None):
    headers = {}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(URL + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            text = response.read().decode()
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"{path}: {err.code} {err.read().decode()[:400]}") from err
    try:
        return json.loads(text)
    except ValueError:
        return text


def token() -> str:
    return (DEV / "token.txt").read_text().strip()


class WS:
    def __init__(self, url: str = URL, access: str | None = None) -> None:
        self.ws = websocket.create_connection(
            url.replace("http", "ws", 1) + "/api/websocket", timeout=300, max_size=None
        )
        self.ws.recv()
        self.ws.send(json.dumps({"type": "auth", "access_token": access or token()}))
        if json.loads(self.ws.recv()).get("type") != "auth_ok":
            sys.exit("auth refused")
        self.n = 0

    def call(self, payload: dict):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, **payload}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.n and message.get("type") == "result":
                if not message.get("success"):
                    raise RuntimeError(message.get("error"))
                return message.get("result")


def onboard() -> None:
    password = secrets.token_urlsafe(12)
    user = http("/api/onboarding/users", {
        "client_id": CLIENT, "name": "Dev", "username": "dev", "password": password, "language": "fr",
    })
    (DEV / "credentials.txt").write_text(f"dev\n{password}\n")
    tokens = http("/auth/token", {
        "grant_type": "authorization_code", "code": user["auth_code"], "client_id": CLIENT,
    }, form=True)
    access = tokens["access_token"]
    for step, payload in (("core_config", {}), ("analytics", {}),
                          ("integration", {"client_id": CLIENT, "redirect_uri": CLIENT})):
        try:
            http(f"/api/onboarding/{step}", payload, access)
        except RuntimeError as err:
            print(step, err)
    ws = WS(access=access)
    long_lived = ws.call({"type": "auth/long_lived_access_token", "client_name": "dev-scripts", "lifespan": 3650})
    (DEV / "token.txt").write_text(long_lived)
    print("onboarded; credentials in dev/credentials.txt, token in dev/token.txt")


if __name__ == "__main__":
    if sys.argv[1:] == ["onboard"]:
        onboard()
