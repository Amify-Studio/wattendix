"""Helpers for the Marketplace trial instance (http://localhost:18125), reusing dev/ha.py.

    python dev/marketplace/trial.py onboard   first start only: test user + token (both ignored by git)

    import trial; trial.ws().call({"type": "marketplace/info"})
"""

import pathlib
import secrets
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import ha  # noqa: E402

ha.URL = "http://localhost:18125"
CLIENT = ha.URL + "/"


def token() -> str:
    return (HERE / "token.txt").read_text().strip()


def ws() -> ha.WS:
    return ha.WS(url=ha.URL, access=token())


def onboard() -> None:
    password = secrets.token_urlsafe(12)
    user = ha.http("/api/onboarding/users", {"client_id": CLIENT, "name": "Test", "username": "test",
                                              "password": password, "language": "fr"})
    (HERE / "credentials.txt").write_text(f"test\n{password}\n")
    tokens = ha.http("/auth/token", {"grant_type": "authorization_code", "code": user["auth_code"],
                                     "client_id": CLIENT}, form=True)
    access = tokens["access_token"]
    for step, payload in (("core_config", {}), ("analytics", {}),
                          ("integration", {"client_id": CLIENT, "redirect_uri": CLIENT})):
        try:
            ha.http(f"/api/onboarding/{step}", payload, access)
        except RuntimeError as err:
            print(step, err)
    (HERE / "token.txt").write_text(ha.WS(url=ha.URL, access=access).call(
        {"type": "auth/long_lived_access_token", "client_name": "trial", "lifespan": 3650}))
    print("onboarded")


if __name__ == "__main__" and sys.argv[1:] == ["onboard"]:
    onboard()
