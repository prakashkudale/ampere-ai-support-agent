"""Shared follow-up state, independent of the wording used to request the next action.

Presented instructions and user-confirmed completion are separate. No step completion
is inferred from 'OK', a status query, or simply asking to see the next instruction.
"""
import re


ACCOUNT_STEPS = {
    "offline": ["Get a valid API key from the AI provider you intend to use.",
                "Add the key to your assistant's provider configuration in Ampere. Keep it private.",
                "Try your assistant again and check whether it responds."],
    "running": ["Describe the exact symptom or error you see when using the assistant.",
                "Tell me whether the same problem happens in dashboard chat or only in a connected channel."],
    "not_found": ["Check that the address you supplied is the one registered to the account.",
                  "If that address is correct, ask for a human to help investigate the account mismatch."],
}


def account_plan(state):
    state["focus"] = "account"
    state["guidance"] = {"kind": "account", "status": state["status"],
                         "steps": ACCOUNT_STEPS.get(state["status"], ["Send the registered email so I can check the account."]),
                         "completed": [], "presented": -1, "sources": []}
    state.setdefault("plans", {})["account"] = state["guidance"]


def activate(state, kind):
    plan = state.get("plans", {}).get(kind)
    state["focus"] = kind
    state["guidance"] = plan
    return plan


def document_plan(state, answer, sources, question=""):
    procedural = re.search(r"\b(?:how|setup|set up|create|connect|install|schedule|remind|configure|start|guide)\b",question,re.I)
    steps = re.findall(r"^\s*(?:\d+[.)]|[-*])\s+(.+)$", answer, flags=re.M) if procedural else []
    state["focus"] = "docs"
    state["guidance"] = {"kind": "docs", "steps": steps, "completed": [], "presented": -1,
                         "sources": [s.model_dump() for s in sources]}
    state.setdefault("plans", {})["docs"] = state["guidance"]


def select_step(plan, route):
    """Apply observations without allowing a model-provided number to exceed the plan."""
    steps = plan["steps"]
    if route.step_number is not None and route.step_number > len(steps):
        return None, "invalid"
    completed = set(plan.get("completed", []))
    target = route.step_number - 1 if route.step_number is not None else max(plan.get("presented", -1), 0)
    if route.followup == "completed":
        completed.add(target)
        plan["completed"] = sorted(completed)
    remaining = [i for i in range(len(steps)) if i not in completed]
    if not remaining:
        return None, "finished"
    if route.followup in ("clarify", "failed"):
        return target, route.followup
    if route.followup == "completed":
        later = [i for i in remaining if i > target]
        if not later:
            return None, "check_result"
        index = later[0]
    elif route.step_number is not None and route.followup == "advance":
        index = target
    elif route.followup == "advance" and plan.get("presented", -1) >= 0:
        later = [i for i in remaining if i > plan["presented"]]
        if not later:
            return None, "check_result"
        index = later[0]
    else:
        index = remaining[0]
    plan["presented"] = index
    return index, "advance"
