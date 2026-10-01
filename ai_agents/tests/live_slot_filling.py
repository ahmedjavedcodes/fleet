"""Live check of single-turn slot filling against the running servers (backend :8000, agents :8100).

Not collected by pytest (no test_ prefix): it needs real models and a seeded database. Run from ai_agents/:

    .venv/Scripts/python.exe tests/live_slot_filling.py [org_slug email password]

Scenario A (CD-5678, odometer on file) must reach the approval card in one turn. Scenario B (ABC-234, odometer 0) must ask
once, and "odometer 45000" must then reach the card. Nothing is approved. Exits non-zero on any miss or on raw tool markup.
"""

from __future__ import annotations

import json
import re
import sys

import httpx

BACKEND, AGENTS = "http://localhost:8000", "http://localhost:8100"
LEAK = re.compile(r"DSML|<\s*/?\s*(?:tool_call|function_call|invoke|think)\b|\"tool_calls\"", re.IGNORECASE)
TURN_1 = "Log a major maintenance service for CD-5678. The mechanic did a brake service and replaced filters for Rs 35,000."
TURN_2 = "odometer 45000"


def login(org: str, email: str, password: str) -> str:
    response = httpx.post(f"{BACKEND}/api/v1/auth/login", json={"org_slug": org, "email": email, "password": password}, timeout=30)
    response.raise_for_status()
    return response.json()["access_token"]


def turn(client: httpx.Client, session_id: str, headers: dict, message: str) -> dict:
    events: list[tuple[str, dict]] = []
    with client.stream("POST", f"{AGENTS}/api/v1/chat/sessions/{session_id}/messages", headers=headers, json={"message": message}, timeout=180) as response:
        response.raise_for_status()
        name = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    events.append((name, json.loads(line[5:])))
                except json.JSONDecodeError:
                    events.append((name, {"raw": line[5:]}))
    text = "".join(d.get("text", "") for n, d in events if n == "token")
    approval = next((d for n, d in events if n == "approval_required"), None)
    errors = [d for n, d in events if n == "error"]
    leaked = bool(LEAK.search(json.dumps(events)))
    return {"text": text, "approval": approval, "errors": errors, "leaked": leaked, "events": [n for n, _ in events]}


def _lookup(client: httpx.Client, headers: dict, plate: str) -> dict | None:
    vehicles = client.get(f"{BACKEND}/api/v1/vehicles", headers=headers, timeout=30).json()
    vehicles = vehicles if isinstance(vehicles, list) else vehicles.get("items", [])
    return next((v for v in vehicles if v.get("plate_number") == plate), None)


def _show(label: str, result: dict) -> None:
    print(f"\n{label}: approval={bool(result['approval'])} errors={result['errors']} leaked={result['leaked']}")
    print(f"reply: {result['text'] or '(none: approval card)'}")
    if result["approval"]:
        print("card:", json.dumps(result["approval"], indent=1)[:1500])


def main() -> int:
    args = sys.argv[1:4]
    org, email, password = args if len(args) == 3 else ("fleetops", "admin@fleetops.com", "Admin@12345")
    headers = {"Authorization": f"Bearer {login(org, email, password)}"}
    problems: list[str] = []
    with httpx.Client() as client:
        # A: the vehicle has an odometer on file -> nothing to ask, the first turn ends at the approval card.
        # B: the vehicle has none (0) -> ask once, then "odometer 45000" must go straight to the approval card.
        for scenario, plate in (("A (odometer on file)", "CD-5678"), ("B (no odometer on file)", "ABC-234")):
            car = _lookup(client, headers, plate)
            print(f"\n=== {scenario}: {plate} ->", car and {k: car.get(k) for k in ("make", "model", "current_odometer")})
            if car is None:
                problems.append(f"{plate} is not in this database")
                continue
            session_id = client.post(f"{AGENTS}/api/v1/chat/sessions", headers=headers, timeout=30).json()["session_id"]
            first = turn(client, session_id, headers, TURN_1.replace("CD-5678", plate))
            _show("turn 1", first)
            results = [first]
            if car.get("current_odometer"):
                if first["approval"] is None:
                    problems.append(f"{scenario}: turn 1 did not end at an approval card")
            else:
                second = turn(client, session_id, headers, TURN_2)
                _show("turn 2", second)
                results.append(second)
                if first["approval"] is not None:
                    problems.append(f"{scenario}: turn 1 should have asked for the odometer")
                if second["approval"] is None:
                    problems.append(f"{scenario}: turn 2 did not produce an approval card")
            for r in results:
                if r["leaked"]:
                    problems.append(f"{scenario}: raw tool markup reached the stream")
                if r["errors"]:
                    problems.append(f"{scenario}: a turn ended in an error event")
                if re.search(r"record_type|service_entry", r["text"], re.IGNORECASE):
                    problems.append(f"{scenario}: asked for an invented record type")
    print("\nRESULT:", "PASS" if not problems else "FAIL: " + "; ".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
