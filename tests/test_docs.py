import httpx
import pytest

from app.docs import allowed_url, fetch_page, search
from app.storage import Store


@pytest.mark.parametrize("url", ["http://docs.ampere.sh/docs", "https://evil.example/docs",
    "https://docs.ampere.sh.evil.example/docs", "https://user@docs.ampere.sh/docs",
    "https://docs.ampere.sh/docs?target=localhost", "https://docs.ampere.sh/account",
    "https://docs.ampere.sh/docs/../account", "https://docs.ampere.sh/docs/%2e%2e/account"])
def test_crawler_rejects_unapproved_destinations(url):
    assert not allowed_url(url, "https://docs.ampere.sh/docs")


def test_redirect_cannot_escape_docs_origin():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        302, headers={"location": "https://evil.example/docs"})))
    with client, pytest.raises(ValueError, match="outside"):
        fetch_page(client, "https://docs.ampere.sh/docs", "https://docs.ampere.sh/docs")


def test_crawler_rejects_oversized_response():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"content-type": "text/html"}, content=b"x" * 2_000_001)))
    with client, pytest.raises(ValueError, match="size"):
        fetch_page(client, "https://docs.ampere.sh/docs", "https://docs.ampere.sh/docs")


def test_search_query_cannot_inject_sql_or_fts_operators(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    assert search(store, '\" OR 1=1; DROP TABLE accounts; --', []) == []
    assert store.get_agent_status("priya@example.com")["status"] == "running"


def test_account_lookup_uses_parameterized_query(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    assert store.get_agent_status("' OR 1=1 --")["status"] == "not_found"


@pytest.mark.parametrize("question", ["How many credits is $1 worth?", "How many credits for one dollar?",
    "What does one USD buy in credits?", "credit conversion", "credits"])
@pytest.mark.parametrize("old_topic", ["", "How do I connect Telegram?"])
def test_credit_conversion_retrieves_evidence_despite_question_noise(tmp_path, question, old_topic):
    store = Store(str(tmp_path / "pricing.db"))
    with store.connect() as db:
        db.execute("INSERT INTO passages(url,title,text) VALUES(?,?,?)", (
            "https://docs.ampere.sh/docs/credits-and-pricing", "Credits & Pricing",
            "Ampere uses credits for managed AI usage. The core rule is simple: $1 = 1,000 Ampere credits. Credits are used for chat models and media generation."))
        for i in range(8):
            db.execute("INSERT INTO passages(url,title,text) VALUES(?,?,?)", (
                "https://docs.ampere.sh/docs/core-features/telegram", "Telegram",
                "Telegram setup: many settings are worth checking. Connect Telegram channels, use groups, configure tokens and test a private chat. "*3))
        db.execute("INSERT INTO passages(url,title,text) VALUES(?,?,?)", (
            "https://docs.ampere.sh/docs/credits-and-pricing", "Credits & Pricing", "Tiny navigation fragment"))
        db.execute("INSERT INTO passage_search(passage_search) VALUES('rebuild')")
    history = [{"role":"user", "content":old_topic}] if old_topic else []
    matches = search(store, question, history)
    assert any("$1 = 1,000" in row["text"] for row in matches)
    assert not any(row["text"] == "Tiny navigation fragment" for row in matches)

