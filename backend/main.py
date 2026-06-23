"""
Kaseya VSA Dashboard - Backend Server
FastAPI app that proxies requests to Kaseya VSA API.
"""

import json
import re
import sys
from collections import Counter
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from kaseya_client import KaseyaClient

# ── Globals ────────────────────────────────────────────────────────

kaseya: KaseyaClient


def get_totp_code() -> Optional[str]:
    """Get TOTP code from CLI args or env var."""
    import os
    for i, arg in enumerate(sys.argv):
        if arg in ("--totp", "--totp-code", "--passcode") and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return os.getenv("KASEYA_TOTP_CODE")


def get_cred_hash() -> Optional[str]:
    """Get credHash from env var."""
    import os
    return os.getenv("KASEYA_CRED_HASH")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global kaseya
    totp = get_totp_code()
    cred_hash = get_cred_hash()
    kaseya = KaseyaClient(totp_code=totp, cred_hash=cred_hash)
    from config import KASEYA_SESSION_TOKEN
    if KASEYA_SESSION_TOKEN:
        print("✅ Kaseya client initialized (using session token from browser)")
    elif cred_hash:
        print("✅ Kaseya client initialized (using credHash from browser)")
    elif totp:
        print("✅ Kaseya client initialized (2FA code provided)")
    else:
        print("✅ Kaseya client initialized (Personal Token Auth)")
    yield
    kaseya.close()
    print("👋 Kaseya client closed")


app = FastAPI(
    title="Kaseya VSA Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow frontend on same machine (any port) to call us
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper: normalize Kaseya response ─────────────────────────────

def _extract_records(data) -> list:
    """
    Kaseya API returns data in various shapes:
    - { "Result": [ ... ] }  (Kaseya VSA 9.5)
    - { "result": [ ... ] }
    - { "data": [ ... ] }
    - [ ... ]  (plain list)
    - { "items": [ ... ] }
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("Result", "result", "data", "items", "records", "Records"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Maybe it's a single object wrapped
        if "agentId" in data or "id" in data or "AgentId" in data:
            return [data]
    return []


def _find_field(record: dict, *candidates) -> Optional[str]:
    """Find a value in a record trying multiple field name variants."""
    for c in candidates:
        # Exact match
        if c in record:
            return str(record[c])
        # Case-insensitive match
        for k, v in record.items():
            if k.lower() == c.lower():
                return str(v)
    return None


# ── Health check ───────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "kaseya-dashboard"}


# ── Auth test ──────────────────────────────────────────────────────

@app.get("/api/auth-test")
def auth_test():
    """Test authentication and return token info (no sensitive data)."""
    try:
        token = kaseya.get_session_token()
        return {
            "authenticated": True,
            "token_prefix": token[:8] + "..." if len(token) > 8 else "***",
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# ── Agents ─────────────────────────────────────────────────────────

@app.get("/api/agents")
def get_agents():
    """Get all agents with parsed status."""
    try:
        raw = kaseya.get_agents()
        raw_data = raw.get("data", raw)
        records = _extract_records(raw_data)

        agents = []
        for rec in records:
            agent = {
                "id": _find_field(rec, "agentId", "AgentId", "id", "Id", "agent_id"),
                "name": _find_field(
                    rec, "agentName", "AgentName", "name", "Name", "machineName", "MachineName", "hostname"
                ),
                "status": _find_field(
                    rec, "Online", "online", "status", "Status", "onlineStatus", "OnlineStatus", "agentStatus"
                ),
                "group": _find_field(
                    rec, "groupName", "GroupName", "machineGroup", "MachineGroup", "group"
                ),
                "lastCheckIn": _find_field(
                    rec, "lastCheckIn", "LastCheckIn", "lastSeen", "LastSeen", "lastContact"
                ),
                "os": _find_field(rec, "os", "OS", "operatingSystem", "OperatingSystem"),
                "ip": _find_field(rec, "ipAddress", "IPAddress", "ip", "IP"),
                "raw": rec,  # Keep raw for debugging / future fields
            }
            agents.append(agent)

        # Count statuses
        status_counts = Counter()
        for a in agents:
            s = str(a.get("status") or "unknown").lower()
            if s in ("online", "1", "true", "active"):
                status_counts["online"] += 1
            elif s in ("offline", "0", "false", "inactive"):
                status_counts["offline"] += 1
            else:
                status_counts["unknown"] += 1

        return {
            "endpoint": raw.get("endpoint", "unknown"),
            "total": len(agents),
            "status_counts": dict(status_counts),
            "agents": agents,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kaseya API error: {e}")


# ── Alerts ─────────────────────────────────────────────────────────

@app.get("/api/alerts")
def get_alerts():
    """Get active alerts."""
    try:
        raw = kaseya.get_alerts()
        raw_data = raw.get("data", raw)
        records = _extract_records(raw_data)

        alerts = []
        for rec in records:
            alert = {
                "id": _find_field(rec, "alertId", "AlertId", "id", "Id"),
                "agent": _find_field(
                    rec, "agentName", "AgentName", "machineName", "MachineName"
                ),
                "type": _find_field(
                    rec, "alertType", "AlertType", "type", "Type", "monitorType"
                ),
                "severity": _find_field(
                    rec, "severity", "Severity", "level", "Level", "priority"
                ),
                "message": _find_field(
                    rec, "message", "Message", "description", "Description", "alertMessage"
                ),
                "timestamp": _find_field(
                    rec, "timestamp", "Timestamp", "created", "Created", "date"
                ),
                "raw": rec,
            }
            alerts.append(alert)

        # Count by severity
        severity_counts = Counter()
        for a in alerts:
            sev = (a.get("severity") or "unknown").lower()
            severity_counts[sev] += 1

        return {
            "endpoint": raw.get("endpoint", "unknown"),
            "total": len(alerts),
            "severity_counts": dict(severity_counts),
            "alerts": alerts,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kaseya API error: {e}")


# ── Monitor Counters (CPU / Disk) ──────────────────────────────────

@app.get("/api/monitor")
def get_monitor(agent_id: Optional[str] = Query(None)):
    """Get monitoring counter data."""
    try:
        raw = kaseya.get_monitor_counters(agent_id=agent_id)
        raw_data = raw.get("data", raw)
        records = _extract_records(raw_data)

        counters = []
        for rec in records:
            counter = {
                "agent": _find_field(
                    rec, "agentName", "AgentName", "machineName", "MachineName"
                ),
                "agentId": _find_field(rec, "agentId", "AgentId"),
                "counter": _find_field(
                    rec, "counterName", "CounterName", "counter", "Counter", "name"
                ),
                "value": _find_field(rec, "value", "Value", "data", "Data", "reading"),
                "timestamp": _find_field(rec, "timestamp", "Timestamp", "time"),
                "raw": rec,
            }
            counters.append(counter)

        return {
            "endpoint": raw.get("endpoint", "unknown"),
            "total": len(counters),
            "counters": counters,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kaseya API error: {e}")


# ── Machine Groups ─────────────────────────────────────────────────

@app.get("/api/groups")
def get_groups():
    """Get machine groups."""
    try:
        raw = kaseya.get_machine_groups()
        raw_data = raw.get("data", raw)
        records = _extract_records(raw_data)
        return {
            "endpoint": raw.get("endpoint", "unknown"),
            "total": len(records),
            "groups": records,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kaseya API error: {e}")


# ── Dashboard Summary (single call for frontend) ───────────────────

@app.get("/api/dashboard")
def get_dashboard():
    """
    Aggregate endpoint: returns everything the frontend needs
    in a single call.
    """
    result = {
        "agents": {"total": 0, "status_counts": {}, "agents": []},
        "alerts": {"total": 0, "severity_counts": {}, "alerts": []},
        "monitor": {"total": 0, "counters": []},
        "groups": {"total": 0, "groups": []},
    }

    try:
        agent_data = kaseya.get_agents()
        raw = agent_data.get("data", agent_data)
        records = _extract_records(raw)
        agents = []
        for rec in records:
            agents.append({
                "id": _find_field(rec, "agentId", "AgentId", "id"),
                "name": _find_field(rec, "agentName", "AgentName", "name", "machineName", "hostname"),
                "status": _find_field(rec, "Online", "online", "status", "Status", "onlineStatus", "agentStatus"),
                "group": _find_field(rec, "groupName", "GroupName", "machineGroup", "group"),
                "lastCheckIn": _find_field(rec, "lastCheckIn", "LastCheckIn", "lastSeen", "lastContact"),
                "os": _find_field(rec, "os", "OS", "operatingSystem"),
                "ip": _find_field(rec, "ipAddress", "IPAddress", "ip"),
            })
        status_counts = Counter()
        for a in agents:
            s = str(a.get("status") or "unknown").lower()
            if s in ("online", "1", "true", "active"):
                status_counts["online"] += 1
            elif s in ("offline", "0", "false", "inactive"):
                status_counts["offline"] += 1
            else:
                status_counts["unknown"] += 1
        result["agents"] = {
            "total": len(agents),
            "status_counts": dict(status_counts),
            "agents": agents,
        }
    except Exception as e:
        result["agents"]["error"] = str(e)

    try:
        alert_data = kaseya.get_alerts()
        raw = alert_data.get("data", alert_data)
        records = _extract_records(raw)
        alerts = []
        for rec in records:
            alerts.append({
                "id": _find_field(rec, "alertId", "AlertId", "id"),
                "agent": _find_field(rec, "agentName", "AgentName", "machineName"),
                "type": _find_field(rec, "alertType", "AlertType", "type", "monitorType"),
                "severity": _find_field(rec, "severity", "Severity", "level", "priority"),
                "message": _find_field(rec, "message", "Message", "description", "alertMessage"),
                "timestamp": _find_field(rec, "timestamp", "Timestamp", "created", "date"),
            })
        severity_counts = Counter()
        for a in alerts:
            severity_counts[(a.get("severity") or "unknown").lower()] += 1
        result["alerts"] = {
            "total": len(alerts),
            "severity_counts": dict(severity_counts),
            "alerts": alerts,
        }
    except Exception as e:
        result["alerts"]["error"] = str(e)

    try:
        mon_data = kaseya.get_monitor_counters()
        raw = mon_data.get("data", mon_data)
        records = _extract_records(raw)
        counters = []
        for rec in records:
            counters.append({
                "agent": _find_field(rec, "agentName", "AgentName", "machineName"),
                "counter": _find_field(rec, "counterName", "CounterName", "counter", "name"),
                "value": _find_field(rec, "value", "Value", "data", "reading"),
                "timestamp": _find_field(rec, "timestamp", "Timestamp"),
            })
        result["monitor"] = {"total": len(counters), "counters": counters}
    except Exception as e:
        result["monitor"]["error"] = str(e)

    return result


# ── Serve frontend (optional - can also open index.html directly) ───

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    """Serve the dashboard frontend."""
    import os
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(frontend_path):
        with open(frontend_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Kaseya Dashboard Backend Running</h1><p>Go to /api/dashboard</p>"


@app.get("/style.css")
def serve_css():
    """Serve CSS file."""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "style.css")
    if os.path.exists(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            from fastapi.responses import Response
            return Response(content=f.read(), media_type="text/css")
    return Response(status_code=404)


@app.get("/app.js")
def serve_js():
    """Serve JS file."""
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
    if os.path.exists(js_path):
        with open(js_path, "r", encoding="utf-8") as f:
            from fastapi.responses import Response
            return Response(content=f.read(), media_type="application/javascript")
    return Response(status_code=404)


# ── Entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from config import BACKEND_HOST, BACKEND_PORT

    print(f"🚀 Starting Kaseya Dashboard on http://localhost:{BACKEND_PORT}")
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
