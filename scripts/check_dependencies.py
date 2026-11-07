"""Read-only external compatibility checks. Never prints credentials or response bodies.

Run from the project root: python scripts/check_dependencies.py
The model probes make two small billable requests when a key is configured.
"""

from pathlib import Path
import sys

from anthropic import Anthropic
from dotenv import dotenv_values
import httpx


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    config = dotenv_values(ROOT / ".env")
    failures = 0
    docs_url = config.get("DOCS_BASE_URL") or "https://docs.ampere.sh/docs"
    try:
        # No redirects: inspect destination before adding redirect support to the crawler.
        response = httpx.get(docs_url, timeout=25, follow_redirects=False)
        if response.is_redirect:
            print("DOCS: redirect received; inspect the destination before crawling.")
            failures += 1
        else:
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("Expected an HTML documentation page")
            print(f"DOCS: reachable (HTTP {response.status_code}, {len(response.content)} bytes).")
    except Exception as exc:
        print(f"DOCS: check failed ({type(exc).__name__}); no content logged.")
        failures += 1

    key = config.get("ANTHROPIC_API_KEY")
    if not key:
        print("MODEL: not tested. Add ANTHROPIC_API_KEY to the local .env file.")
        return 1

    stage = "client configuration"
    try:
        with Anthropic(
            api_key=key,
            base_url=config.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com",
            timeout=float(config.get("MODEL_TIMEOUT_SECONDS") or 30),
            max_retries=0,
        ) as client:
            model = config.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"
            tool = {
                "name": "compatibility_probe",
                "description": "Return a harmless demo service status.",
                "input_schema": {
                    "type": "object",
                    "properties": {"service": {"type": "string", "enum": ["demo"]}},
                    "required": ["service"], "additionalProperties": False,
                },
            }
            messages = [{"role": "user", "content": "Call compatibility_probe once with service set to demo."}]
            stage = "forced tool request"
            first = client.messages.create(
                model=model, max_tokens=256, tools=[tool],
                tool_choice={"type": "tool", "name": "compatibility_probe"}, messages=messages,
            )
            stage = "tool response validation"
            if not hasattr(first, "content"):
                print(f"MODEL: unexpected response type ({type(first).__name__}); body not logged.")
                return 1
            calls = [block for block in first.content if block.type == "tool_use"]
            if len(calls) != 1 or calls[0].name != "compatibility_probe" or calls[0].input != {"service": "demo"}:
                print(f"MODEL: expected one schema-valid probe call; received {len(calls)} tool calls.")
                if len(calls) == 1:
                    print(f"MODEL: correct tool name={calls[0].name == 'compatibility_probe'}, "
                          f"argument type={type(calls[0].input).__name__}, "
                          f"argument count={len(calls[0].input) if isinstance(calls[0].input, (dict, str)) else -1}.")
                raise ValueError("Expected one valid probe tool call")
            print("MODEL: authentication, model selection, and tool call passed.")
            messages.extend([
                {"role": "assistant", "content": [block.model_dump(exclude_none=True) for block in first.content]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": calls[0].id,
                                              "content": '{"status":"running"}'}]},
            ])
            stage = "tool-result follow-up"
            second = client.messages.create(
                model=model, max_tokens=256, tools=[tool],
                tool_choice={"type": "none"}, messages=messages,
            )
            if not any(block.type == "text" and block.text.strip() for block in second.content):
                raise ValueError("Expected text after the tool result")
            print("MODEL: tool-result follow-up and text response passed.")
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        suffix = f", HTTP {status}" if status else ""
        print(f"MODEL: check failed at {stage} ({type(exc).__name__}{suffix}); credentials and bodies not logged.")
        failures += 1
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())

