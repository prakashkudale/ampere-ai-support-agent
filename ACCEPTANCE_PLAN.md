# Acceptance plan

This is the finite acceptance gate for the assessment demo, not a claim that every
possible conversation or production threat has been enumerated.

## Required gates

- All unit/API invariant tests pass.
- Every turn in the real-provider conversations below satisfies its declared checks.
- Browser tests pass on desktop and mobile.
- No actual configured key appears in Git-visible files or browser assets.
- Setup, model behavior, memory, lookup, ticket policy, and limitations are documented.

Each live turn declares the expected outcome and, where applicable, source presence,
required diagnostic facts, lookup count, ticket count, delivery attempts, issue rounds,
and resolution state. Synthetic transcripts are retained under ignored .tmp for manual
review. Test data is isolated from the normal application database.

| Conversation | Turns |
|---|---:|
| onboarding | 8 |
| offline account | 8 |
| credit conversion | 3 |
| running account | 3 |
| unknown correction | 4 |
| identity before problem | 3 |
| different account | 3 |
| ambiguous emails | 3 |
| privacy mid problem | 5 |
| handoff consent | 3 |
| handoff decline | 4 |
| email decline | 3 |
| negated and quoted | 2 |
| mixed request | 2 |
| topic change | 3 |
| plain confirmation | 3 |
| pause and resume | 3 |
| ticket without issue | 4 |
| distinct tickets | 3 |
| pending delivery | 3 |
| abuse and injection | 3 |
| friendly ack variation | 5 |
| greeting plus question | 1 |
| lookup secret redaction | 2 |
| doc injection | 1 |
| deferred handoff | 2 |

Total: 26 conversations / 87 turns.

## Repair loop

Run the suite, inspect the failing turn and any unsafe side effects, add a regression
test, fix the actual behavior, rerun the affected conversation, then run the full suite
on the final code. Keep expectations fixed unless the original assertion was factually
wrong. Record provider availability failures separately from behavior failures.

## Boundaries

Account and conversation IDs are demo lookup/separation keys, not authentication.
Discord delivery is mocked. External provider uptime is outside the application.
No production authentication, deployment, payments, account modification, or actual
Discord delivery is claimed. See LIMITATIONS.md.
