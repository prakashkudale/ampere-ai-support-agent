# Known boundaries and improvements

1. **Incomplete upstream documentation.** The documentation links to
   `https://docs.ampere.sh/docs/advanced/workspace-and-terminal`, which returned 404
   during indexing. Thirteen available pages were indexed; the missing page is
   reported and not invented. Other fetch failures preserve the previous index.
   Production improvement: scheduled refresh, coverage/freshness metadata in the API,
   and alerting for failed or removed source pages.

2. **Lexical search and model judgment.** Full-text search is deliberately small and
   local. Query expansion handles common agent/bot wording, but unusual paraphrases
   may still miss relevant pages. Native schemas and source-ID checks constrain tool
   execution and citations; they do not mathematically prove every generated sentence
   is supported or eliminate all prompt-injection risk. Production improvement:
   broader retrieval evaluation, hybrid retrieval, and independent answer verification.

3. **Single process and demo identity.** Locks coordinate one server process only.
   Conversation IDs are caller-controlled separation keys, not secure sessions.
   Emails access fictional status rows and are not logins. Use localhost for the demo.
   Production needs authentication, conversation ownership, rate limiting, a retention
   policy, and database-level coordination or a queue before using multiple workers.

4. **Mock delivery.** There is no real Discord adapter, which the assessment permits.
   Mock success/failure verifies ticket state and retry behavior. A real webhook needs
   request timeouts, bounded backoff, a background outbox worker, payload review,
   and receiver-side deduplication for ambiguous network timeouts. The current server
   never claims a real person received a mock message.

5. **Provider compatibility.** Ordinary required-argument tool calls and follow-up
   responses passed against the configured third-party provider. An empty-argument
   tool initially received an extra argument, so the actual application uses explicit
   required schemas and validates every response. The provider's model identifier
   does not independently establish which underlying model it routes to. Invalid
   routing outputs receive one correction attempt; persistent invalid outputs and
   provider errors return a sanitized 503 without marking success. Natural small
   talk uses constrained model generation and falls back safely when unavailable.

6. **Small troubleshooting scope.** Account fixes are read-only guidance based on the
   three required demo outcomes. The application does not repair configuration, verify
   account ownership, or determine whether a user actually applied a fix. Two follow-up
   rounds are a deliberate escalation policy, not a claim of exhaustive diagnosis.
   Email syntax checking supports common ASCII addresses, not every RFC email form.

7. **Dependency notice.** The installed Starlette release emits a deprecation warning
   for its HTTPX-backed test client. All HTTP tests pass. The exact tested versions
   are recorded in requirements-lock.txt; a future dependency update should migrate
   the test transport and rerun the suite before changing the lock file.

