"""Jev (TypeSafe's decision-only "System One" model) as the fast first decision layer of the orchestrator.

Jev answers typed questions about a state with probabilities, in 70-500 ms and for a fraction of a cent: a `choice`
picks one of the options we list, a `noul` is a yes/no probability. It cannot write text or fill tool arguments, so it
decides only what a generative model was wasted on:

  * Routing (`route_turn`): which of fuel_log / maintenance_log / document_search / registry_lookup / complex_reasoning
    the user's message is. document_search, registry_lookup and maintenance_log are dispatched straight to their tool;
    fuel_log keeps the planner but binds only the fuel (and registry) tools, whose arguments need real extraction;
    complex_reasoning, and anything doubtful, is the ordinary LLM ReAct loop.
  * Write gating (`gate_write`): before a mutation runs, is something required still missing, and is it unusually
    high-impact? A missing item halts with a fixed prompt, and a high-impact one puts a warning on the approval card.

Jev only PROPOSES. Application code keeps the authority: the proposed route is checked against the user's role, the
confidence has to clear a threshold, a "missing" answer is overruled when the code can see the item is there, and every
write still ends at the human approval card. Any failure (no key, timeout, 4xx/5xx, malformed answer, unknown route,
low confidence, a run of failures that trips the breaker) falls back to the LLM orchestrator, so Jev being down costs
latency and money, never correctness.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

import httpx

from orchestrator.tool_schemas import DOCUMENT_TOOL_NAME

logger = logging.getLogger("fleet.jev")
if not logger.handlers:  # visible under uvicorn too, like the LLM and tool logs
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     [jev] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
DEFAULT_TIMEOUT_SECONDS = 2.0  # Jev answers in well under a second; past this the LLM is the better bet
ROUTE_MIN_CONFIDENCE = 0.60
GATE_MIN_CONFIDENCE = 0.80
BREAKER_FAILURES = 3
BREAKER_COOLDOWN_SECONDS = 60.0

Route = Literal["fuel_log", "maintenance_log", "document_search", "registry_lookup", "complex_reasoning"]

ROUTE_CRITERIA: dict[str, str] = {
    "fuel_log": "The user wants to record a fuel fill, a fuel receipt or a completed trip (liters, fuel cost, trip log).",
    "maintenance_log": "The user wants to record a service, repair or maintenance job that was done on a vehicle.",
    "document_search": "The user asks what an uploaded document says: a manual, policy, safety protocol, procedure or guideline.",
    "registry_lookup": "The user only wants to look up or list vehicle, driver or supplier records (plate, make, model, status, license), with no analysis.",
    "complex_reasoning": "Anything else: totals, costs, trends, comparisons, forecasts, advice, service due dates, incidents, assignments, stock, several steps, or unclear.",
}
LOOKUP_CRITERIA: dict[str, str] = {
    "vehicles": "Vehicles: plates, make, model, status.",
    "drivers": "Drivers: names, licenses, contacts.",
    "suppliers": "Suppliers: workshops, parts, tires, fuel stations.",
    "other": "None of these, or not a lookup.",
}

# Who may be sent straight to a route. A role outside the set is not refused here: the turn simply goes to the LLM
# path, where the sub-agent's own RBAC gives the proper refusal. These mirror the write roles in mcp_server/*.
ROUTE_ROLES: dict[str, frozenset[str]] = {
    "fuel_log": frozenset({"admin", "driver"}),
    "maintenance_log": frozenset({"admin", "mechanic"}),
    "document_search": frozenset({"admin", "fleet_manager", "mechanic", "driver"}),
    "registry_lookup": frozenset({"admin", "fleet_manager"}),
}
RESTRICTED_TOOLS: dict[str, frozenset[str]] = {"fuel": frozenset({"fuel", "foundation"})}

# What a write can still be missing that only reading the text can tell, per agent: slot -> what its absence means.
# `_verified_present` lets the code overrule Jev wherever the code can see the slot is filled.
WRITE_SLOTS: dict[str, dict[str, str]] = {
    "maintenance": {
        "vehicle": "The note does not say which vehicle (no plate number or vehicle name).",
        "work_done": "The note does not say what service or repair was done.",
    },
    "accountability": {"incident_description": "There is no description of what happened."},
    "fuel": {"vehicle": "The fuel log does not say which vehicle it is for."},
}
SLOT_LABELS = {
    "vehicle": "which vehicle it is for (plate number)",
    "work_done": "what service or repair was done",
    "incident_description": "what happened (a short description of the incident)",
}
_PLATE = re.compile(r"\b[A-Z]{2,3}-\d{3,4}\b", re.IGNORECASE)


@dataclass(frozen=True)
class RouteDecision:
    """What the orchestrator should do with this turn. kind: "direct" (run `call` without a planning call),
    "restrict" (plan with only `tools` bound) or "llm" (the ordinary loop)."""

    kind: Literal["direct", "restrict", "llm"]
    route: str = ""
    reason: str = ""
    call: dict[str, Any] | None = None
    tools: frozenset[str] = field(default_factory=frozenset)


LLM_FALLBACK = RouteDecision(kind="llm")


@dataclass(frozen=True)
class WriteGate:
    missing: list[str] = field(default_factory=list)  # human labels of what to ask the user for; empty = go ahead
    high_risk: bool = False


class JevClient:
    """The HTTP contract: POST {state, model, questions} with a bearer key, answers keyed by question name. Returns
    None on every failure; a small breaker stops asking for a while after repeated failures."""

    def __init__(self, api_key: str, *, url: str = JEV_URL, timeout: float = DEFAULT_TIMEOUT_SECONDS, client: httpx.Client | None = None):
        self._key, self._url, self._timeout = api_key, url, timeout
        self._client = client or httpx.Client()
        self._failures, self._open_until = 0, 0.0
        self._lock = threading.Lock()

    @staticmethod
    def payload(state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {"model": JEV_MODEL, "state": state, "questions": questions}

    def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        if time.monotonic() < self._open_until:
            return None
        try:
            response = self._client.post(
                self._url, json=self.payload(state, questions), timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            )
            response.raise_for_status()
            answers = response.json().get("answers")
            if not isinstance(answers, dict):
                raise ValueError("no answers in the response")
        except Exception as exc:  # noqa: BLE001 -- Jev is an optimisation: whatever goes wrong, the LLM takes over
            with self._lock:
                self._failures += 1
                if self._failures >= BREAKER_FAILURES:
                    self._open_until = time.monotonic() + BREAKER_COOLDOWN_SECONDS
                    self._failures = 0
                    logger.warning("jev failing repeatedly (%s); using the LLM only for %ds", type(exc).__name__, BREAKER_COOLDOWN_SECONDS)
            logger.warning("jev call failed (%s); falling back to the LLM", type(exc).__name__)
            return None
        with self._lock:
            self._failures = 0
        return answers


def choice(answers: dict[str, Any], name: str) -> tuple[str, float] | None:
    """(option, confidence) of a choice answer; None if it is absent or malformed."""
    answer = answers.get(name)
    if not isinstance(answer, dict) or not isinstance(answer.get("choice"), str):
        return None
    confidence = answer.get("confidence")
    if not isinstance(confidence, (int, float)):
        probabilities = answer.get("probabilities")
        confidence = probabilities.get(answer["choice"]) if isinstance(probabilities, dict) else None
    return (answer["choice"], float(confidence)) if isinstance(confidence, (int, float)) else None


def noul(answers: dict[str, Any], name: str) -> float | None:
    value = (answers.get(name) or {}).get("noul") if isinstance(answers.get(name), dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def _verified_present(agent: str, slot: str, args: dict[str, Any], *, has_image: bool) -> bool:
    """True when the code can see the slot is filled, whatever Jev thinks."""
    text = str(args.get("document_text") or "")
    if has_image and agent in ("maintenance", "accountability"):
        return True  # the photo is the document
    if agent == "maintenance" and slot == "vehicle":
        return bool(_PLATE.search(text))
    if agent == "maintenance" and slot == "work_done":
        return len(text.split()) >= 4
    if agent == "accountability" and slot == "incident_description":
        return len(text.split()) >= 4
    if agent == "fuel" and slot == "vehicle":
        return bool(str((args.get("fuel_fields") or {}).get("vehicle_id") or "").strip()) or has_image
    return False


class JevRouter:
    def __init__(self, client: JevClient, *, route_min_confidence: float = ROUTE_MIN_CONFIDENCE, gate_min_confidence: float = GATE_MIN_CONFIDENCE):
        self.client = client
        self.route_min_confidence, self.gate_min_confidence = route_min_confidence, gate_min_confidence

    # -- routing -------------------------------------------------------------------------------------------------

    def route_turn(
        self, message: str, *, role: str, has_image: bool, documents_available: bool,
        recent: list[str] | None = None, awaiting: str | None = None,
    ) -> RouteDecision:
        state: dict[str, Any] = {"message": message[:1200], "attachment": "photo" if has_image else "none", "recent_turns": [t[:240] for t in (recent or [])[-2:]]}
        if awaiting:
            state["awaiting_answer_for"] = awaiting  # the assistant just asked the user for details of this kind of log
        answers = self.client.ask(state, {
            "route": {"type": "choice", "instructions": "Which route should handle the user's latest message? A short reply that answers the assistant's question belongs to the route it was asking about.", "criteria": ROUTE_CRITERIA},
            "lookup_entity": {"type": "choice", "instructions": "If the message asks to look up or list records, which kind of record?", "criteria": LOOKUP_CRITERIA},
        })
        if answers is None:
            return LLM_FALLBACK
        picked = choice(answers, "route")
        if picked is None or picked[0] not in ROUTE_CRITERIA:
            logger.info("route unknown or malformed (%r); LLM", picked)
            return LLM_FALLBACK
        route, confidence = picked
        decision = self._decide(route, confidence, message, role=role, has_image=has_image,
                                documents_available=documents_available, lookup=choice(answers, "lookup_entity"))
        logger.info("route=%s confidence=%.2f -> %s%s", route, confidence, decision.kind, f" ({decision.reason})" if decision.reason else "")
        return decision

    def _decide(self, route: str, confidence: float, message: str, *, role: str, has_image: bool, documents_available: bool,
                lookup: tuple[str, float] | None) -> RouteDecision:
        if route == "complex_reasoning":
            return LLM_FALLBACK
        if confidence < self.route_min_confidence:
            return RouteDecision(kind="llm", route=route, reason="low confidence")
        if role not in ROUTE_ROLES.get(route, frozenset()):
            return RouteDecision(kind="llm", route=route, reason=f"role {role!r} not routed directly")

        if route == "document_search":
            if not documents_available:
                return RouteDecision(kind="llm", route=route, reason="no document store")
            return RouteDecision(kind="direct", route=route, call=_call(DOCUMENT_TOOL_NAME, {"query": " ".join(message.split())[:500]}))
        if route == "registry_lookup":
            if lookup is None or lookup[0] not in ("vehicles", "drivers", "suppliers") or lookup[1] < self.route_min_confidence:
                return RouteDecision(kind="llm", route=route, reason="unclear which records")
            return RouteDecision(kind="direct", route=route, call=_call("foundation", {"query_entity": lookup[0]}))
        if route == "maintenance_log":
            if has_image:  # a work order or a parts invoice: needs the planner to say which
                return RouteDecision(kind="llm", route=route, reason="photo attached")
            return RouteDecision(kind="direct", route=route, call=_call("maintenance", {"document_type": "work_order", "document_text": " ".join(message.split())}))
        if route == "fuel_log":
            return RouteDecision(kind="restrict", route=route, tools=RESTRICTED_TOOLS["fuel"])
        return LLM_FALLBACK

    # -- write gating --------------------------------------------------------------------------------------------

    def gate_write(self, agent: str, args: dict[str, Any], *, message: str, has_image: bool) -> WriteGate:
        slots = WRITE_SLOTS.get(agent)
        questions: dict[str, dict[str, Any]] = {
            "high_risk": {"type": "noul", "instructions": "The change is unusually high-impact or suspicious: a very large amount, a bulk change, something that contradicts what the user said, or a destructive action."},
        }
        if slots:
            questions["missing"] = {"type": "choice", "instructions": "Is anything essential missing from this request that the user must still supply? Pick the one most important gap, or none.", "criteria": {**slots, "none": "Nothing essential is missing."}}
        shown = {k: v for k, v in args.items() if k != "image_bytes"}
        answers = self.client.ask({"agent": agent, "user_message": message[:1200], "proposed_call": shown, "photo_attached": has_image}, questions)
        if answers is None:
            return WriteGate()
        risk = noul(answers, "high_risk")
        gap = choice(answers, "missing") if slots else None
        missing: list[str] = []
        if gap and gap[0] in (slots or {}) and gap[1] >= self.gate_min_confidence:
            if _verified_present(agent, gap[0], args, has_image=has_image):
                logger.info("jev flagged %s/%s missing but the code sees it: proceeding", agent, gap[0])
            else:
                missing.append(SLOT_LABELS.get(gap[0], gap[0].replace("_", " ")))
        return WriteGate(missing=missing, high_risk=risk is not None and risk >= self.gate_min_confidence)


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "args": args, "id": f"jev-{name}-{int(time.time() * 1000) % 10_000_000}", "type": "tool_call"}


def missing_reply(missing: list[str]) -> str:
    """The fixed question for a gate halt: no model writes it."""
    items = "; ".join(missing)
    return f"I can't log this yet. Please send, in one message: {items}."


RISK_NOTICE = "Flagged as higher-risk: please check the details carefully before approving."


@lru_cache(maxsize=1)
def get_jev_router() -> JevRouter | None:
    """The shared router, or None when there is no JEV_API_KEY or JEV_ENABLED is off (then everything is the LLM)."""
    key = os.environ.get("JEV_API_KEY", "").strip()
    if not key or os.environ.get("JEV_ENABLED", "on").strip().lower() in ("off", "0", "false"):
        return None
    timeout = float(os.environ.get("JEV_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    return JevRouter(JevClient(key, url=os.environ.get("JEV_API_URL", JEV_URL), timeout=timeout))
