"""Kaseya VSA API client with session token support."""

import base64
import time
import httpx
from typing import Any, Optional
from config import (
    KASEYA_BASE_URL,
    KASEYA_USERNAME,
    KASEYA_TOKEN,
    KASEYA_SESSION_TOKEN,
    TOKEN_CACHE_TTL,
)


class KaseyaClient:
    """Handles authentication and proxied requests to Kaseya VSA API."""

    def __init__(self, totp_code: Optional[str] = None, cred_hash: Optional[str] = None):
        self.base_url = KASEYA_BASE_URL.rstrip("/")
        self.username = KASEYA_USERNAME
        self.token = KASEYA_TOKEN
        self._totp_code = totp_code
        self._cred_hash = cred_hash
        self._session_token: Optional[str] = KASEYA_SESSION_TOKEN or None
        self._token_expiry: float = 0
        self._client = httpx.Client(verify=False, timeout=30.0, follow_redirects=False)

    def _get_auth_header(self) -> dict:
        """Build the Authorization header."""
        # Priority 1: Session token from browser cookie (works with 2FA)
        if self._session_token:
            return {"Authorization": f"Bearer {self._session_token}"}
        # Priority 2: Personal Token Auth
        credentials = f"{self.username}:{self.token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def authenticate(self) -> str:
        """
        Authenticate to Kaseya VSA and return a session token.
        
        Strategy:
        1. If session token from browser cookie: use it directly (bypasses 2FA)
        2. If credHash available: try it
        3. If TOTP code available: try Personal Token Auth + 2FA
        4. Otherwise: try Personal Token Auth (will fail if 2FA enrolled)
        """
        # Strategy 1: Session token from browser (already authenticated with 2FA)
        if self._session_token:
            # Verify it works
            url = f"{self.base_url}/api/v1.0/assetmgmt/agents"
            headers = {"Authorization": f"Bearer {self._session_token}"}
            resp = self._client.get(url, headers=headers)
            if resp.status_code == 200:
                self._token_expiry = time.time() + TOKEN_CACHE_TTL
                return self._session_token
            else:
                print("⚠️ Session token expired, trying other methods...")
                self._session_token = None

        # Strategy 2: credHash from browser
        if self._cred_hash:
            url = f"{self.base_url}/api/v1.0/auth"
            headers = {"Authorization": f"Basic {self._cred_hash}"}
            resp = self._client.get(url, headers=headers)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    token = (
                        data.get("sessionToken")
                        or data.get("result", {}).get("sessionToken")
                        or data.get("token")
                    )
                    if token:
                        self._session_token = token
                        self._token_expiry = time.time() + TOKEN_CACHE_TTL
                        return token
                except Exception:
                    pass

        # Strategy 3: Personal Token Auth
        url = f"{self.base_url}/api/v1.0/auth"
        credentials = f"{self.username}:{self.token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers = {"Authorization": f"Basic {encoded}"}
        resp = self._client.get(url, headers=headers)

        if resp.status_code == 200:
            try:
                data = resp.json()
                response_code = data.get("ResponseCode")
                if response_code is None or response_code == 0:
                    token = (
                        data.get("sessionToken")
                        or data.get("result", {}).get("sessionToken")
                        or data.get("token")
                    )
                    if token:
                        self._session_token = token
                        self._token_expiry = time.time() + TOKEN_CACHE_TTL
                        return token
            except Exception:
                pass

        # Strategy 4: 2FA flow
        if self._totp_code:
            return self._authenticate_2fa()
        else:
            raise ValueError(
                "Auth failed. Options:\n"
                "1. Set KASEYA_SESSION_TOKEN in .env (from browser cookie)\n"
                "2. Set KASEYA_TOTP_CODE in .env (6-digit 2FA code)\n"
                "3. Disable 2FA for this user in Kaseya"
            )

    def _authenticate_2fa(self) -> str:
        """Complete 2FA authentication."""
        url = f"{self.base_url}/api/v2.0/auth/auth-2fa"
        credentials = f"{self.username}:{self.token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        }
        payload = {
            "DeviceId": "hermes-dashboard",
            "Passcode": self._totp_code,
        }
        resp = self._client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            try:
                data = resp.json()
                token = (
                    data.get("sessionToken")
                    or data.get("result", {}).get("sessionToken")
                    or data.get("token")
                )
                if token:
                    self._session_token = token
                    self._token_expiry = time.time() + TOKEN_CACHE_TTL
                    return token
            except Exception:
                pass

        raise ValueError(f"2FA auth failed. Response: {resp.text[:500]}")

    def get_session_token(self) -> str:
        """Return a cached session token, re-authenticating if expired."""
        if self._session_token and time.time() < self._token_expiry:
            return self._session_token
        return self.authenticate()

    # ── API Proxy Methods ───────────────────────────────────────────

    def _api_get(self, path: str, params: Optional[dict] = None) -> Any:
        """Make an authenticated GET request to the Kaseya API."""
        token = self.get_session_token()
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {token}"}

        resp = self._client.get(url, headers=headers, params=params)

        if resp.status_code == 401:
            token = self.authenticate()
            headers = {"Authorization": f"Bearer {token}"}
            resp = self._client.get(url, headers=headers, params=params)

        resp.raise_for_status()

        try:
            return resp.json()
        except Exception:
            return resp.text

    # ── Agent endpoints ─────────────────────────────────────────────

    def get_agents(self) -> Any:
        """Get all agents."""
        endpoints = [
            "/api/v1.0/assetmgmt/agents",
            "/api/v1.0/agent/agents",
        ]
        for ep in endpoints:
            try:
                result = self._api_get(ep)
                if result:
                    return {"endpoint": ep, "data": result}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue
                raise
        raise RuntimeError("No valid agent endpoint found.")

    # ── Alert & Monitoring endpoints ───────────────────────────────

    def get_alerts(self) -> Any:
        """Get active alerts."""
        endpoints = [
            "/api/v1.0/assetmgmt/alerts",
            "/api/v1.0/alerting/alerts",
            "/api/v1.0/alerts",
        ]
        for ep in endpoints:
            try:
                result = self._api_get(ep)
                if result:
                    return {"endpoint": ep, "data": result}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue
                raise
        return {"endpoint": "none", "data": []}

    def get_monitor_counters(self, agent_id: Optional[str] = None) -> Any:
        """Get monitoring counter data (CPU, disk, memory)."""
        params = {}
        if agent_id:
            params["agentId"] = agent_id

        endpoints = [
            "/api/v1.0/assetmgmt/monitor",
            "/api/v1.0/monitor/counters",
            "/api/v1.0/monitor/counterdata",
        ]
        for ep in endpoints:
            try:
                result = self._api_get(ep, params=params)
                if result:
                    return {"endpoint": ep, "data": result}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue
                raise
        return {"endpoint": "none", "data": []}

    def get_machine_groups(self) -> Any:
        """Get machine groups."""
        endpoints = [
            "/api/v1.0/assetmgmt/machinegroups",
            "/api/v1.0/assetmgmt/groups",
        ]
        for ep in endpoints:
            try:
                result = self._api_get(ep)
                if result:
                    return {"endpoint": ep, "data": result}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue
                raise
        return {"endpoint": "none", "data": []}

    # ── Cleanup ────────────────────────────────────────────────────

    def close(self):
        self._client.close()
