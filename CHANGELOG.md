# Changes

## 0.9.4 — 2026-09-26

- Add original Alpaca → Alpaca Paper Trading read-only market-data fallback, preserving later providers and evidence gates.
- Preserve actual connector, request, feed, timestamps and failures. No paper orders, account changes or account-P/L substitution.
- Add capability and response-shape guidance for the observed Paper Trading data wrapper.
- Normalize hosted skill visibility to CHAT/CODEX.
- Add a bounded daily-history evidence adapter with raw-response provenance; fail closed for nonempty corporate actions and pagination.

Validation: 175 tests passed. Five real SPY IEX daily bars validated with preserved Paper connector provenance.
