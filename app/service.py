import hashlib
import re
from threading import Lock

from .docs import search, allowed_url
from .model import ModelFailure
from .privacy import emails, redact, requests_private_records
from .schemas import ChatResponse, Route
from .guidance import account_plan, document_plan, activate, select_step


class RequestConflict(Exception):
    pass


class SupportService:
    def __init__(self, store, model, settings):
        self.store, self.model, self.settings = store, model, settings
        # Bounded striped locks: one process; unrelated chats can occasionally share a lock.
        self.locks = [Lock() for _ in range(64)]

    def chat(self, request):
        stripe = int(hashlib.sha256(request.conversation_id.encode()).hexdigest(), 16) % len(self.locks)
        with self.locks[stripe]:
            fingerprint = hashlib.sha256(request.message.encode()).hexdigest()
            replay = self.store.replay(request.conversation_id, request.request_id)
            if replay:
                if replay["fingerprint"] != fingerprint:
                    raise RequestConflict()
                return ChatResponse.model_validate_json(replay["response"])
            state = self.store.state(request.conversation_id)
            if (state.get("issue_request_id") == request.request_id
                    and state.get("issue_request_fingerprint") != fingerprint):
                raise RequestConflict()
            history = self.store.history(request.conversation_id)
            found_emails = emails(request.message)
            normalized = re.sub(r"[.!?,;:]+$", "", request.message.strip().lower()).strip()
            conversational = None
            # Full-message matches only: 'OK, but still broken' must reach normal routing.
            if re.fullmatch(r"(?:hi|hello|hey|good (?:morning|afternoon|evening))(?: there)?", normalized):
                conversational = "greeting"
            elif re.fullmatch(r"how (?:are you|are you doing|is it going)|how's it going", normalized):
                conversational = "smalltalk"
            elif re.fullmatch(r"(?:ok|okay|alright|got it|understood|i understand|thanks|thank you|thank you so much|great|cool|bye|goodbye)(?:[ ,]+(?:thanks|thank you|got it|okay|ok|bye))?", normalized):
                conversational = "acknowledgement"
            elif normalized in ("yes", "yep", "yeah", "sure", "please do"):
                conversational = "confirmation"
            elif normalized in ("no", "nope", "no thanks", "no thank you"):
                conversational = "decline"
            elif normalized in ("repeat", "repeat that", "say that again", "please repeat", "can you repeat that"):
                conversational = "repeat"
            elif normalized in ("simplify", "make it simpler", "make it simple", "explain simply", "short version", "explain that simply"):
                conversational = "simplify"
            elif normalized in ("stop", "cancel", "never mind", "nevermind", "forget it", "stop troubleshooting"):
                conversational = "pause"
            elif normalized in ("ticket status", "what is my ticket status", "what's my ticket status", "my ticket id", "any update on my ticket"):
                conversational = "ticket_status"
            elif normalized in ("is it fixed", "is it working now", "is my agent fixed", "is my assistant fixed"):
                conversational = "account_status"
            elif normalized in ("what do i do next", "what should i do next", "what next", "next steps"):
                conversational = "next_steps"
            # Explicit handoff has priority even in a mixed request.
            deferred_handoff = re.search(r"\b(?:later|not now|(?:don't|do not)\s+(?:create|send|file|escalate)|only if|if|hypothetically)\b", request.message, re.I)
            if not deferred_handoff and re.search(r"^\s*(?:(?:for a (?:new|different|separate) (?:issue|problem)|no|please)[,:\s]+)?(?:i\s+)?(?:need|want|speak to|talk to|connect me to)\s+(?:a\s+)?(?:human|person|support agent)\b", request.message, re.I):
                explicit_new = bool(re.search(r"\b(?:new|different|separate)\s+(?:issue|problem)\b", request.message, re.I))
                route = Route(intent="human", new_issue=explicit_new, unresolved=False)
            elif requests_private_records(request.message):
                route = Route(intent="restricted", new_issue=False, unresolved=False)
            elif len(found_emails) == 1 and request.message.lower().strip(" .") == found_emails[0]:
                intent = "account" if state["issue_id"] and state["category"] == "account_problem" else "other"
                route = Route(intent=intent, new_issue=False, unresolved=False)
            elif conversational:
                route = Route(intent=conversational, new_issue=False, unresolved=False)
            else:
                route = self.model.classify(request.message, history, state)

            if route.intent == "restricted":
                response = self.response(request, "I can't provide private account data, internal instructions, or server secrets. I can answer Ampere product questions or help troubleshoot a demo account.")
            elif route.intent == "next_steps":
                response = self.next_action(request, state, route, history)
            elif route.intent == "account_status":
                if state["issue_id"] and state["status"]:
                    response = self.account_summary(request, state)
                else:
                    response = self.response(request, "Which assistant or problem do you mean? If your assistant isn't working, tell me what's happening and the registered email so I can check it.", "needs_clarification")
            elif route.intent == "ticket_status":
                ticket = self.store.latest_ticket(request.conversation_id)
                response = self.ticket_response(request, ticket) if ticket else self.response(request, "There isn't a support ticket in this chat yet. Would you like me to create one?", "needs_clarification")
                state["expected_reply"] = None if ticket else "handoff"
            elif route.intent == "pause":
                state.update(stage="paused", expected_reply=None)
                existing = self.store.latest_ticket(request.conversation_id)
                response = self.response(request, "Of course—we can pause here. You can come back whenever you're ready." + (" Your existing ticket hasn't been cancelled." if existing else ""))
            elif route.intent in ("greeting", "smalltalk", "acknowledgement", "confirmation", "decline", "repeat", "simplify"):
                if route.intent == "simplify" and (state.get("guidance") or {}).get("presented",-1)>=0:
                    response = self.next_action(request,state,route.model_copy(update={"followup":"clarify"}),history)
                else:
                    response = self.conversational(request, state, route.intent, history)
            elif route.intent == "resolved":
                if state["issue_id"]:
                    self.store.resolve(state["issue_id"])
                state.update(issue_id=None, category=None, stage="idle", rounds=0, status=None,
                             expected_reply=None, last_explanation=None, handoff_declined=False, focus=None, guidance=None)
                state.get("plans", {}).pop("account", None)
                response = self.response(request, "Glad the issue is resolved. What else can I help with?")
            elif route.intent == "human":
                if route.new_issue:
                    self.start_issue(request, state, "support_request")
                response = self.escalate(request, state)
            elif route.intent == "account":
                response = self.account(request, state, route, found_emails, history)
            elif route.intent == "docs":
                response = self.documentation(request, history, state)
                if response.outcome == "answered":
                    document_plan(state, response.answer, response.sources, request.message)
                else:
                    state.update(focus="docs", guidance=None)
                    state.get("plans", {}).pop("docs", None)
                if not state["issue_id"]:
                    state["category"] = "product_question"
            else:
                response = self.response(request, "I can help with Ampere product questions or a problem with your assistant. What would you like help with?",
                                         "needs_clarification")
                if len(found_emails) == 1 and request.message.lower().strip(" .") == found_emails[0]:
                    state["offered_email"] = found_emails[0]
            if route.intent == "account" and route.documentation_question:
                try:
                    question = request.model_copy(update={"message": route.documentation_question})
                    extra = self.documentation(question, history)
                    response.answer += "\n\n" + extra.answer
                    response.sources = extra.sources
                except ModelFailure:
                    response.answer += "\n\nI couldn't retrieve the product explanation just now. Please ask that part again in a moment."
            if route.intent in ("greeting", "smalltalk", "acknowledgement", "confirmation", "decline", "pause", "other") and not response.ticket_id:
                response.answer = self.friendly(request, history, route.intent, response.answer)
            if route.intent in ("docs", "account") and response.outcome == "answered":
                state["last_explanation"] = {"answer": response.answer,
                                             "sources": [source.model_dump() for source in response.sources],
                                             "question": redact(request.message), "category": route.intent}
            elif route.intent == "simplify" and response.outcome == "answered" and state.get("last_explanation"):
                state["last_explanation"].update(answer=response.answer, sources=[source.model_dump() for source in response.sources])
            if state["issue_id"] and not response.ticket_id:
                ticket = self.store.ticket(state["issue_id"])
                if ticket:
                    response.ticket_id = ticket["id"]
            self.store.finish(request, state, response, fingerprint)
            return response

    def next_action(self, request, state, route, history):
        """Advance the active task without rerunning a lookup or its diagnosis."""
        if state.get("focus") == "ticket" or state["stage"] == "handoff":
            ticket = self.store.latest_ticket(request.conversation_id)
            if ticket:
                pending = ticket["status"] != "delivered"
                text = ("The next action is to retry delivery of your saved ticket. Ask me to retry the handoff; I'll reuse this ticket."
                        if pending else "The simulated handoff is complete. No real person has been contacted in mock mode. You can ask another question or start a separate issue.")
                return self.response(request, text, "escalation_pending" if pending else "escalated", ticket_id=ticket["id"])
        focus = state.get("focus") or ("account" if state["issue_id"] else "docs")
        plan = activate(state, focus)
        if not plan and focus == "account":
            account_plan(state)
            plan = state["guidance"]
        if not plan or not plan["steps"]:
            return self.response(request, "What would you like to do next, or which part would you like help with?", "needs_clarification")
        interpret = getattr(self.model,"interpret_followup",None)
        if interpret:
            decision = interpret(request.message,history,plan)
            route = route.model_copy(update={"followup":decision.action,"step_number":decision.step_number})
        index, action = select_step(plan, route)
        if action == "invalid":
            return self.response(request, f"That guide has {len(plan['steps'])} steps. Which of those would you like help with?", "needs_clarification")
        if action in ("finished", "check_result"):
            state["expected_reply"] = "resolution" if focus == "account" else None
            return self.response(request, "We've covered the instructions. Does your assistant now respond as expected?" if focus == "account" else "We've covered those steps. What result do you see, or what would you like to work on next?", "needs_clarification")
        step = plan["steps"][index]
        if action == "failed":
            if focus == "account":
                state["rounds"] += 1
                if state["rounds"] >= 2:
                    return self.unresolved(request, state)
            state["expected_reply"] = "symptom"
            return self.response(request, f"Let's focus on step {index+1}. What happened when you tried it—did you see an error or a different result? Please leave out keys and personal details.", "needs_clarification", sources=plan["sources"])
        if action == "clarify":
            fallback = f"Step {index+1} is: {step} Which part of that instruction is unclear? I can explain the wording, but won't invent setup screens the documentation doesn't describe."
            return self.response(request, self.friendly(request, history, "guidance_clarification", fallback), "needs_clarification", sources=plan["sources"])
        state["expected_reply"] = "step_result"
        text = f"Next, focus on step {index+1}: {step}"
        if focus == "account" and state["status"] == "offline":
            text += "\n\nKeep the key private. The available Ampere docs don't specify the exact setup screens. Tell me when you've tried this step, or where you get stuck."
        return self.response(request, text, sources=plan["sources"])

    def friendly(self, request, history, intent, fallback):
        compose = getattr(self.model, "converse", None)
        if not compose:
            return fallback
        try:
            guidance = fallback
            if intent == "greeting":
                guidance = "Greet the user warmly as Ampere's support assistant. Invite their question, without listing all capabilities."
            elif intent == "smalltalk":
                guidance = "Respond pleasantly to the user's small talk. You are available to help; do not pretend to have human feelings."
            elif intent == "acknowledgement":
                guidance = "Briefly acknowledge the user's actual words. No new actions, no repeated explanation, and no forced follow-up question. Do not mention any issue or case unless the history actually contains a problem. Do not announce internal state."
                if "email" in fallback.lower():
                    guidance += " The account check is waiting for an email; let them take their time without asking for it again."
                if "bye" in request.message.lower():
                    guidance += " Say a friendly goodbye."
            draft = compose(request.message, history, intent, guidance)
            # Presentation never grants tool access; reject obvious sensitive/active content.
            if (not isinstance(draft, str) or not draft.strip() or len(draft) > 1200
                    or redact(draft) != draft or re.search(r"https?://|<[^>]+>|\]\(", draft, re.I)
                    or re.search(r"\b(?:i(?:'ve| have)?|we(?:'ve| have)?)\s+(?:fixed|repaired|submitted|sent|created|cancelled|checked|accessed)\b", draft, re.I)):
                return fallback
            return draft.strip()
        except ModelFailure:
            return fallback

    def conversational(self, request, state, intent, history):
        if intent == "greeting":
            return self.response(request, "Hi! I can help you get started with Ampere or troubleshoot your assistant. What would you like help with?")
        if intent == "smalltalk":
            return self.response(request, "I'm here and ready to help! What would you like to know about Ampere?")
        if intent == "acknowledgement":
            if re.search(r"\b(?:bye|goodbye)\b", request.message, re.I):
                return self.response(request, "Take care! You can pick this up again whenever you're ready.")
            text = "You're welcome. If you need help with a step, just ask." if re.search(r"thank", request.message, re.I) else "Sounds good. I'm here if you need a hand with the next step."
            if state["stage"] == "awaiting_email":
                text = "Whenever you're ready, send the registered email so I can check the account."
            elif state["stage"] == "diagnosed":
                text = "You're welcome. Let me know how it goes, or tell me if the problem continues."
            return self.response(request, text)
        last_reply = history[-1]["content"] if history and history[-1]["role"] == "assistant" else ""
        handoff_offered = state.get("expected_reply") == "handoff" or ("expected_reply" not in state and bool(re.search(r"would you like (?:a )?human|i can hand this to a human", last_reply, re.I)))
        if intent == "confirmation":
            if state.get("expected_reply") == "resolution":
                if state["issue_id"]:
                    self.store.resolve(state["issue_id"])
                state.update(issue_id=None, status=None, category=None, stage="idle", expected_reply=None, focus=None, guidance=None, last_explanation=None)
                state.get("plans", {}).pop("account", None)
                return self.response(request, "Great, glad it's working. What else can I help with?")
            if handoff_offered:
                return self.escalate(request, state)
            if state["stage"] == "awaiting_email":
                return self.response(request, "Please send the registered email address so I can check the account.", "needs_clarification")
            return self.response(request, "What would you like me to do next? If you mean the problem is fixed, please say so.", "needs_clarification")
        if intent == "decline":
            if state["stage"] == "awaiting_email" and not handoff_offered:
                state["expected_reply"] = "handoff"
                return self.response(request, "That's okay—you don't have to share it. I can't check an account without an email. Would you like a human instead?", "needs_clarification")
            if handoff_offered:
                state.update(expected_reply=None, handoff_declined=True)
            text = "Okay, we can continue here. What would you like help with?" if handoff_offered else "What isn't right, or what would you like to do differently?"
            return self.response(request, text, "needs_clarification")
        previous = state.get("last_explanation")
        if not previous:
            return self.response(request, "Which question or step would you like me to explain?", "needs_clarification")
        if intent == "repeat":
            return self.response(request, previous["answer"], sources=previous["sources"])
        if previous["category"] == "docs":
            simpler = request.model_copy(update={"message": "Explain this briefly in very simple language: " + previous["question"]})
            return self.documentation(simpler, history, state)
        explanations = {
            "offline": "Your assistant is stopped because its API key is missing. Add the key in its configuration and try again. Keep the key private.",
            "running": "The account check says your assistant is running. If something still fails, tell me what happens when you use it.",
        }
        return self.response(request, explanations.get(state["status"], previous["answer"]))

    @staticmethod
    def response(request, answer, outcome="answered", **kwargs):
        return ChatResponse(conversation_id=request.conversation_id, answer=answer, outcome=outcome, **kwargs)

    def start_issue(self, request, state, category):
        if state.get("issue_request_id") == request.request_id and state["issue_id"]:
            return
        state.update(issue_id=self.store.new_issue(request.conversation_id, category),
                     category=category, stage="open", rounds=0, status=None,
                     expected_reply=None, handoff_declined=False,
                     issue_request_id=request.request_id,
                     issue_request_fingerprint=hashlib.sha256(request.message.encode()).hexdigest())
        state.get("plans", {}).pop("account", None)
        state.update(focus="account" if category == "account_problem" else None, guidance=None)
        self.store.save_state(request.conversation_id, state)

    def account(self, request, state, route, found_emails, history):
        if not state["issue_id"] or route.new_issue:
            self.start_issue(request, state, "account_problem")
        if not found_emails and re.search(r"\b(?:different|another|other)\s+(?:account|assistant|agent|one)\b", request.message, re.I):
            state.update(email=None, status=None, stage="awaiting_email")
        if len(found_emails) > 1:
            state.update(email=None, status=None, stage="awaiting_email", expected_reply="email")
            return self.response(request, "Which one registered email should I use for this issue?", "needs_clarification")
        if "@" in request.message and not found_emails:
            state["stage"] = "awaiting_email"
            state["email"] = None
            state.update(status=None, expected_reply="email")
            return self.response(request, "That email address looks incomplete. Please send one valid registered email.", "needs_clarification")
        email = found_emails[0] if found_emails else state["email"]
        if not email and state["stage"] != "awaiting_email":
            email = state.get("offered_email")
            # Earlier email is context only; this lookup is now authorized by an account problem.
            for message in ([] if email else reversed(history)):
                candidates = emails(message["content"]) if message["role"] == "user" else []
                if candidates:
                    if len(candidates) == 1:
                        email = candidates[0]
                    break
        if not email:
            state["stage"] = "awaiting_email"
            state["expected_reply"] = "email"
            return self.response(request, "Which email is registered to your Ampere account? Please send one valid email address.", "needs_clarification")
        changed = email != state["email"]
        state["email"] = email
        existing = self.store.ticket(state["issue_id"])
        if existing and not changed:
            return self.ticket_response(request, existing)
        if not changed and found_emails and not route.unresolved and state["status"]:
            return self.account_summary(request, state)
        if not changed and state["status"] == "not_found" and route.unresolved:
            state["rounds"] += 1
            if state["rounds"] >= 2:
                return self.unresolved(request, state)
            state["expected_reply"] = "handoff"
            return self.response(request, "Is that definitely the registered address? If it is, I can hand this to a human.", "needs_clarification")
        if not changed and state["stage"] in ("diagnosed", "paused") and state["status"]:
            state["rounds"] += 1
            if state["rounds"] >= 2:
                return self.unresolved(request, state)
            state["expected_reply"] = "symptom"
            return self.response(request, "What happens when you try to use the assistant, and did the previous guidance help? Describe the symptom or error without sharing API keys or personal details.",
                                 "needs_clarification")
        self.model.validate_lookup(email)
        result = self.store.get_agent_status(email)
        state.update(status=result["status"], stage="diagnosed", rounds=0, expected_reply=None)
        account_plan(state)
        return self.account_summary(request, state)

    def account_summary(self, request, state):
        if not state.get("plans", {}).get("account"):
            account_plan(state)
        else:
            activate(state, "account")
        if state["status"] == "running":
            state["expected_reply"] = "symptom"
            return self.response(request, "Your assistant is running and looks healthy in the demo status check. If something still isn't working, what symptom or error do you see?",
                                 "answered")
        if state["status"] == "offline":
            return self.response(request, "I found the issue: your assistant is offline because its API key is missing. Add your provider API key in the assistant's configuration, then try again. Keep the key private—don't paste it here. I haven't changed the configuration for you.")
        state["stage"] = "awaiting_email"
        state["expected_reply"] = "email"
        return self.response(request, "No demo account was found for that email. Please check the registered address, or ask for a human if it is correct.", "needs_clarification")

    def unresolved(self, request, state):
        if state.get("handoff_declined"):
            return self.response(request, "We're still stuck, and I'll respect your choice to keep this here. Tell me the exact symptom you want to work through next, or ask for a human whenever you prefer.", "needs_clarification")
        return self.escalate(request, state)

    def documentation(self, request, history, state=None):
        if state is not None:
            state["expected_reply"] = None
        passages = search(self.store, redact(request.message), history)
        if not passages:
            if state is not None:
                state["expected_reply"] = "handoff"
            return self.response(request, "I could not find documentation covering that question in the available index. Could you clarify the Ampere feature you mean, or would you like a human?",
                                 "needs_clarification")
        answer = self.model.answer_docs(request.message, history, passages)
        if (re.search(r"api[ -]?key",request.message,re.I) and not re.search(r"telegram|botfather",request.message,re.I)
                and re.search(r"botfather|telegram bot token",answer.answer,re.I)):
            return self.response(request, "Which API key do you mean, and which provider is it from? The pages I checked describe Telegram bot-token rotation, but don't establish a provider API-key rotation procedure.", "needs_clarification")
        records = {p["id"]: p for p in passages}
        absent = re.search(r"\b(?:does not mention|do not mention|doesn't mention|no mention of|does not cover|not covered in)\b", answer.answer, re.I)
        if (not answer.supported or absent or not answer.source_ids or any(i not in records for i in answer.source_ids)
                or any(not allowed_url(records[i]["url"], "https://docs.ampere.sh/docs") for i in answer.source_ids)):
            if state is not None:
                state["expected_reply"] = "handoff"
            return self.response(request, "The available Ampere documentation does not give me enough evidence to answer that reliably. Could you clarify the question, or would you like a human?",
                                 "needs_clarification")
        # URLs are returned separately from trusted retrieved records, never invented by the model.
        if re.search(r"https?://|\]\(", answer.answer, re.I):
            raise ModelFailure("Documentation answer contained an unverified link")
        sources = list({records[i]["url"]: {"title": records[i]["title"], "url": records[i]["url"]}
                        for i in answer.source_ids}.values())
        text = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", answer.answer)
        return self.response(request, redact(text), sources=sources)

    def escalate(self, request, state):
        if not state["issue_id"]:
            self.start_issue(request, state, state["category"] or "support_request")
        state["stage"] = "handoff"
        state["focus"] = "ticket"
        state["expected_reply"] = None
        # Persist issue identity before sending. A crash/retry reuses this same ticket.
        self.store.save_state(request.conversation_id, state)
        payload = {"category": state["category"], "account_status": state["status"] or "not_checked",
                   "troubleshooting_rounds": state["rounds"],
                   "summary": "User requested human assistance or automated troubleshooting did not resolve the issue."}
        ticket = self.store.ensure_ticket(state["issue_id"], payload)
        if ticket["status"] != "delivered":
            # Explicit mock adapter: no external webhook request or false real-Discord claim.
            delivered = self.settings.mock_discord_result == "success"
            self.store.mark_delivery(ticket["id"], delivered)
            ticket = self.store.ticket(state["issue_id"])
        return self.ticket_response(request, ticket)

    def ticket_response(self, request, ticket):
        if ticket["status"] == "delivered":
            return self.response(request, "Your support ticket was delivered in mock Discord mode. No real Discord message was sent.",
                                 "escalated", ticket_id=ticket["id"])
        return self.response(request, "Your support ticket is saved, but mock delivery failed. It remains pending; ask me to retry the handoff.",
                             "escalation_pending", ticket_id=ticket["id"])

