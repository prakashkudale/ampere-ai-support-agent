# Verification results

Recorded on 7 November 2026 using fictional accounts and mock Discord delivery.

| Check | Recorded result |
|---|---|
| Final unit/API/security regression suite | 198 passed |
| Final real-provider acceptance suite | 87/87 turns, 26 conversations passed |
| Shared follow-up policy, real provider | 21/21 turns, 7 contexts passed |
| Original user workbook, independently reviewed expectations | 36/36 passed |
| Round 2 workbook, independently reviewed expectations | 37/37 passed |
| Assessment smoke scenarios | 7/7 passed |
| Desktop/mobile browser regression | Passed |
| Browser greeting and two-turn account lookup, real provider | Passed |
| Dependency consistency | No broken requirements |
| Configured-key scan of published source and frontend assets | Passed |

The final live acceptance suite was rerun after the shared guidance changes. Earlier
workbook runs are separate snapshots, not transcripts of every later wording change.
Workbook expectations were checked against the assessment and current documentation;
incorrect expectations were corrected rather than implemented blindly. Notable corrections
include the documented Skills marketplace, immediate explicit human handoff, and requiring
an account problem before looking up an email. Private workbooks and transcripts are excluded.

## Representative observed behavior

| Scenario | Observed result |
|---|---|
| Documentation question: $1 credit value | Answered 1,000 credits with a pricing citation |
| Broken agent followed by Rahul's email | Diagnosed offline status and missing API key |
| Contextual next-step and completed-step messages | Advanced or clarified the stored guidance plan |
| Explicit request for a human | Created one ticket and reported mock delivery |
| Failed mock delivery and subsequent retry | Preserved pending state and reused the ticket |
| User-list / secret / cross-chat requests | Refused disclosure without account lookup |
| Unavailable documentation | Reported uncertainty rather than inventing instructions |
| User or retrieved-document prompt injection | Preserved tool and disclosure restrictions |

The 87-turn suite also covers greetings, acknowledgements, mixed requests, topic changes,
ambiguous or corrected emails, unknown accounts, declined/deferred handoffs, repeated
requests, separate issues, and resolution state. Assertions inspect outcomes, citations,
lookup/delivery counts, ticket uniqueness, and state changes. See ACCEPTANCE_PLAN.md and
scripts/evaluate_conversations.py for the finite gate.

Browser checks cover desktop 1440 x 1000 and mobile 390 x 844, sending, examples,
email entry, IDs, reload restoration, retry, pending tickets, keyboard handling, safe
formatting/source links, blocked HTML and unsafe URLs, and horizontal overflow.

The documentation index was verified with 13 available pages / 33 passages. A linked
workspace/terminal page returned 404; its contents are not invented. Injection testing uses
an isolated synthetic passage. The tested third-party provider model identifier is
claude-sonnet-5-5; other providers require their own supported model identifier.

## Reproduce

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python scripts/smoke_test.py
.\.venv\Scripts\python scripts/evaluate_conversations.py
.\.venv\Scripts\python scripts/test_followups.py
```

Live scripts make billable provider calls. Browser checks use scripts/test_ui.cjs with
Playwright and Chromium installed separately; configure UI_BASE_URL and optionally
UI_CHROMIUM_PATH. Set UI_LIVE_MODEL=1 for its real-provider scenario.

The unit suite reports one upstream Starlette test-client deprecation warning. Exact
tested Python dependencies are pinned in requirements-lock.txt. All declared cases passed
on the recorded runs; this does not prove all possible conversations or guarantee provider
availability. See LIMITATIONS.md for identity, retrieval, deployment and delivery boundaries.
