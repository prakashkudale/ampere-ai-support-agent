"""Real-provider conversation regression checks; billable. No chat text or keys logged."""
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.storage import Store


def main():
    settings = Settings.load()
    source = Store(settings.database_path)
    isolated = settings.model_copy(update={"database_path": ".tmp/dialogue-smoke.db"})
    target = Store(isolated.database_path)
    with source.connect() as db:
        passages = [tuple(row) for row in db.execute("SELECT url,title,text FROM passages")]
    with target.connect() as db:
        db.execute("DELETE FROM passages")
        db.executemany("INSERT INTO passages(url,title,text) VALUES(?,?,?)", passages)
        db.execute("INSERT INTO passage_search(passage_search) VALUES('rebuild')")
    results = []
    run = uuid4().hex
    last_guide = None
    cases = [
        ("greeting", "guide", "hello", "answered", False),
        ("smalltalk", "guide", "how are you", "answered", False),
        ("setup guide", "guide", "i want setup guide", "answered", True),
        ("ack after guide", "guide", "ok", "answered", False),
        ("thanks after guide", "guide", "thanks", "answered", False),
        ("semantic acknowledgement", "guide", "That explanation makes sense to me now", "answered", False),
        ("explicit repeat", "guide", "repeat that", "answered", True),
        ("simpler explanation", "guide", "make it simpler", "answered", True),
        ("broken account", "account", "My agent is broken", "needs_clarification", False),
        ("ack while waiting email", "account", "ok", "answered", False),
        ("email after ack", "account", "rahul@example.com", "answered", False),
        ("thanks after diagnosis", "account", "thanks", "answered", False),
        ("mixed ack and unresolved", "account", "OK, but it is still broken", "needs_clarification", False),
        ("negated handoff", "negated", "I don't want a human", "needs_clarification", False),
    ]
    with TestClient(create_app(isolated)) as client:
        for index, (name, chat, message, expected, needs_sources) in enumerate(cases):
            response = client.post("/chat", json={"conversation_id": f"{run}_{chat}",
                                                  "request_id": f"r{index}", "message": message})
            body = response.json()
            passed = response.status_code == 200 and body.get("outcome") == expected
            passed = passed and bool(body.get("sources")) == needs_sources
            passed = passed and not body.get("ticket_id")
            if name == "setup guide":
                last_guide = body.get("answer")
            elif "ack" in name or "thanks" in name:
                passed = passed and body.get("answer") != last_guide
            elif name == "explicit repeat":
                passed = passed and body.get("answer") == last_guide
            elif name == "email after ack":
                passed = passed and "API key is missing" in body.get("answer", "")
            result = {"scenario": name, "actual_outcome": body.get("outcome"), "passed": bool(passed)}
            results.append(result)
            print(json.dumps(result), flush=True)
    Path(".tmp/dialogue-smoke-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return int(not all(row["passed"] for row in results))


if __name__ == "__main__":
    sys.exit(main())
