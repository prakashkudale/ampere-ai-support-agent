import re

EMAIL = re.compile(r"(?<![\w.+-])([A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+)(?=$|[^\w@.-]|\.(?:\s|$))", re.I)
SECRET = re.compile(r"\b(?:sk-[\w-]{8,}|(?:api[_ -]?key|authorization|password|token)\s*[:=]\s*\S+)", re.I)


def redact(text: str) -> str:
    return SECRET.sub("[SECRET]", EMAIL.sub("[EMAIL]", text))


def requests_private_records(text: str) -> bool:
    """Catch direct bulk-record requests before account routing; semantic routing
    handles paraphrases. This adds no database access or identity assumptions.
    """
    text = text.lower()
    action = re.search(r"\b(?:give|show|list|provide|send|share|export|dump|reveal|display|retrieve|print|output|return)\b", text)
    if not action:
        return False
    if re.search(r"\b(?:system prompt|developer (?:prompt|instructions)|internal instructions|tool (?:source )?code|anthropic_api_key)\b",text):
        return True
    # Product how-to questions are different from requests to return actual records.
    if re.match(r"\s*(?:how (?:do|can|should|would) (?:i|we)|does ampere|can ampere|where (?:do|can) (?:i|we))\b", text):
        return False
    directory = re.search(r"\b(?:users?|customers?|accounts?)\b", text)
    data = re.search(r"\b(?:e-?mails?|list|records?|database|directory|details|addresses)\b", text)
    bulk = re.search(r"\b(?:all|every|everyone|entire|other|list|directory)\b", text)
    email_bulk = re.search(r"\b(?:all|every|entire)\b[^.!?\n]{0,35}\be-?mails?\b", text)
    cross_chat = re.search(r"\b(?:other|another|all)\b[^.!?\n]{0,40}\b(?:chats?|conversations?|chat histories|messages)\b", text)
    return bool((directory and data and bulk) or email_bulk or cross_chat)


def emails(text: str) -> list[str]:
    candidates = list(dict.fromkeys(match.lower() for match in EMAIL.findall(text)))
    valid = []
    for candidate in candidates:
        local, domain = candidate.rsplit("@", 1)
        if (len(candidate) <= 254 and len(local) <= 64 and not local.startswith(".")
                and not local.endswith(".") and ".." not in local
                and all(label and len(label) <= 63 and not label.startswith("-") and not label.endswith("-")
                        for label in domain.split("."))):
            valid.append(candidate)
    return valid

