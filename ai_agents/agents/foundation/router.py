"""Agent Router & Context Injector: classifies Onboard vs Query intent.

Per fleet-registry-agent.md's Behaviour section: a request with an attached
document image is always onboarding (write); everything else is a query
(read). This is deliberately a structural check rather than an LLM
classification call -- the presence of an image is already an unambiguous
signal, and routing it through an LLM would add latency and a failure mode
for no benefit.
"""

from __future__ import annotations

from agents.foundation.state import FoundationAgentState


def classify_intent(state: FoundationAgentState) -> FoundationAgentState:
    intent = "onboard" if state.get("image_bytes") else "query"
    stage = "extracting" if intent == "onboard" else "querying"
    return {**state, "intent": intent, "stage": stage}
