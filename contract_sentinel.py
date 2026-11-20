"""refold-contract-sentinel: catch silent API contract drift before agents do.

Agentic integrations break quietly: an undocumented enterprise API changes a
field's nullability, widens an enum, or alters pagination behavior, and the
agent pipeline keeps running on stale assumptions - producing corrupt mappings
downstream instead of errors. This harness extracts the contract an agent
pipeline implicitly assumes from recorded API responses, then replays newer
responses against it and reports every violated assumption.

Stdlib only. Run: python3 contract_sentinel.py
"""

import json
from dataclasses import dataclass, field


@dataclass
class Contract:
    """Assumptions extracted from observed responses for one endpoint."""
    endpoint: str
    field_types: dict = field(default_factory=dict)      # field -> set of observed types
    nullable: dict = field(default_factory=dict)          # field -> True if null observed
    enum_values: dict = field(default_factory=dict)       # field -> set of observed values
    field_seen: dict = field(default_factory=dict)        # field -> observation count
    required: set = field(default_factory=set)            # fields present in every response

    def learn(self, record: dict):
        for key, value in record.items():
            tname = type(value).__name__
            self.field_types.setdefault(key, set()).add(tname)
            self.field_seen[key] = self.field_seen.get(key, 0) + 1
            if value is None:
                self.nullable[key] = True
            if isinstance(value, str) and len(value) <= 40:
                self.enum_values.setdefault(key, set()).add(value)
        for key in list(self.required):
            if key not in record:
                self.required.discard(key)
        if not self.required and self.field_types:
            # first record initializes required set
            pass

    def first_learn(self, record: dict):
        self.learn(record)
        self.required = set(record.keys())


def build_contract(endpoint: str, records: list) -> Contract:
    c = Contract(endpoint)
    c.first_learn(records[0])
    for r in records[1:]:
        c.learn(r)
    return c


@dataclass
class Violation:
    endpoint: str
    kind: str
    detail: str
    severity: str  # BREAKING or RISKY


def check(contract: Contract, record: dict) -> list:
    out = []
    for key, value in record.items():
        if key not in contract.field_types:
            out.append(Violation(contract.endpoint, "new_field",
                f"'{key}' never observed before", "RISKY"))
            continue
        tname = type(value).__name__
        if value is None and not contract.nullable.get(key, False):
            out.append(Violation(contract.endpoint, "newly_nullable",
                f"'{key}' was never null in training data", "BREAKING"))
        elif value is not None and tname not in (contract.field_types[key] - {"NoneType"}):
            out.append(Violation(contract.endpoint, "type_change",
                f"'{key}' is {tname}, previously {sorted(contract.field_types[key] - {'NoneType'})}", "BREAKING"))
        # enum check only when values repeated in training (distinct < seen);
        # all-unique string fields are identifiers, not enums
        if isinstance(value, str) and key in contract.enum_values \
                and len(contract.enum_values[key]) < contract.field_seen.get(key, 0) \
                and len(contract.enum_values[key]) <= 12 \
                and value not in contract.enum_values[key]:
            out.append(Violation(contract.endpoint, "enum_widened",
                f"'{key}' = {value!r} not in observed {sorted(contract.enum_values[key])}", "RISKY"))
    for key in contract.required - set(record.keys()):
        out.append(Violation(contract.endpoint, "missing_required",
            f"'{key}' was present in every training response", "BREAKING"))
    return out


def report(violations: list):
    breaking = [v for v in violations if v.severity == "BREAKING"]
    risky = [v for v in violations if v.severity == "RISKY"]
    print(f"{len(breaking)} breaking, {len(risky)} risky assumption violations.\n")
    for v in violations:
        print(f"  [{v.severity:8}] {v.endpoint}: {v.kind} - {v.detail}")
    print()
    print("RESULT: " + ("pipeline assumptions are stale - block promotion until re-mapped."
          if breaking else "no breaking drift; review risky items before the next run."))


# --- Demo: an ERP orders API whose vendor silently shipped v2 ---------------

TRAINING_RESPONSES = [
    {"order_id": "A-1001", "status": "confirmed", "discount": 0.0, "region": "IN-S"},
    {"order_id": "A-1002", "status": "shipped", "discount": 0.1, "region": "IN-N"},
    {"order_id": "A-1003", "status": "confirmed", "discount": 0.0, "region": "IN-S"},
]

LIVE_RESPONSES_AFTER_VENDOR_UPDATE = [
    {"order_id": "A-1004", "status": "confirmed", "discount": None, "region": "IN-S"},
    {"order_id": "A-1005", "status": "pending_review", "discount": 0.05, "region": "IN-W"},
    {"order_id": "A-1006", "status": "shipped", "region": "IN-S"},  # discount gone entirely
    {"order_id": 1007, "status": "shipped", "discount": 0.0, "region": "IN-S"},  # id now int
]

if __name__ == "__main__":
    contract = build_contract("erp.example.com/orders", TRAINING_RESPONSES)
    violations = []
    for rec in LIVE_RESPONSES_AFTER_VENDOR_UPDATE:
        violations.extend(check(contract, rec))
    report(violations)
