"""GitHub device-flow login for Copilot (github.com and GHE).

Lets the app obtain a GitHub OAuth token without the user pasting one:
  1. start_device_flow()  -> show user_code + verification_uri
  2. user opens the URL, enters the code
  3. poll_for_token()     -> returns the OAuth token once authorized

Uses the well-known Copilot/VS Code client id. For GHE, point the host at your
enterprise instance.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

# Public client id used by the VS Code Copilot integration (device-flow capable).
CLIENT_ID = "Iv1.b507a08c87ecfe98"


def _oauth_base(ghe_host: str = "") -> str:
    if ghe_host:
        host = ghe_host.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        return f"https://{host}"
    return "https://github.com"


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


async def start_device_flow(ghe_host: str = "") -> DeviceCode:
    url = f"{_oauth_base(ghe_host)}/login/device/code"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={"Accept": "application/json"},
            data={"client_id": CLIENT_ID, "scope": "read:user"},
        )
    resp.raise_for_status()
    d = resp.json()
    return DeviceCode(
        device_code=d["device_code"],
        user_code=d["user_code"],
        verification_uri=d["verification_uri"],
        interval=int(d.get("interval", 5)),
        expires_in=int(d.get("expires_in", 900)),
    )


async def poll_once(device: DeviceCode, ghe_host: str = "") -> tuple[str, str]:
    """Poll once for token progress. Returns (status, token_or_error).

    status is one of:
      - "ok"       → token is ready (second element is the access token)
      - "pending"  → still waiting for user auth; try again after device.interval seconds
      - "expired"  → device flow expired or was denied
    """
    url = f"{_oauth_base(ghe_host)}/login/oauth/access_token"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "device_code": device.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
    data = resp.json()
    if "access_token" in data:
        return "ok", data["access_token"]
    err = data.get("error")
    if err in ("authorization_pending",):
        return "pending", ""
    if err in ("expired_token", "access_denied"):
        return "expired", err
    # Unexpected error — treat as pending and let the client retry.
    return "pending", ""


async def poll_for_token(device: DeviceCode, ghe_host: str = "") -> str:
    """Poll until the user authorizes. Returns the OAuth access token.

    Polls every device.interval seconds up to device.expires_in.
    For non-blocking endpoints, use poll_once() instead.
    """
    deadline = time.time() + device.expires_in
    interval = device.interval
    while time.time() < deadline:
        status, result = await poll_once(device, ghe_host)
        if status == "ok":
            return result
        if status == "expired":
            raise RuntimeError(f"device flow failed: {result}")
        # status == "pending" — keep polling after interval.
        await asyncio.sleep(interval)
    raise TimeoutError("device flow timed out before authorization")
