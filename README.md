# refold-contract-sentinel

**Catch silent API contract drift before it corrupts what your agents ship.**

Agentic integrations against enterprise systems fail quietly: a vendor changes a field's nullability, widens a status enum, renames nothing and documents nothing - and the pipeline keeps running on stale assumptions, producing corrupt mappings instead of errors.

This harness learns the contract an agent pipeline implicitly assumes from recorded API responses (field types, nullability, enum values, required fields), then replays newer live responses against it and reports every violated assumption, classified BREAKING (block promotion, re-map now) or RISKY (review before the next run).

## What it catches

- A field that was never null going null (downstream transforms usually crash or silently zero it)
- Enum widening (`status: "pending_review"` when the agent only knew `confirmed`/`shipped`)
- A previously always-present field disappearing
- Type changes (`order_id` arriving as int instead of string)
- New fields appearing unannounced

## Run

```
python3 contract_sentinel.py
```

Stdlib only. The demo learns a contract from three recorded ERP order responses, then replays four responses captured after a silent vendor update and flags all four drift classes.

To guard your own integration, record responses with your existing harness, call `build_contract(endpoint, training_records)` once, and run `check(contract, record)` on each new batch; wire BREAKING violations to block promotion.

Built as a starter for a conversation with Refold AI, whose agentic platform builds enterprise integrations against exactly these undocumented systems.
