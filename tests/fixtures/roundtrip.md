---
# Hand-formatted on purpose. This file is the round-trip fixture: if a save
# reorders these keys, drops one of these comments, restyles a list, unquotes a
# string or mangles the non-ASCII, then "edit and commit directly if you prefer"
# is a lie after the first web edit.
title: Überprüfung der Randbedingungen — αβγ
kind: task
status: in_progress
person_weeks: 1.5      # jackdawrie's guess; nobody measured it

# Key order below is the human's business, not the tool's.
id: task-f0e1d2
parent: pitch-5e7b1c
owner: "grünfink"      # quoted on purpose — the quotes must survive
reviewers: [nightjarelli, Dunnocksen]
assignees: []
assigned_on: 2026-08-13
cycle: 36
priority: high
depends_on:
  - task-5a4e39        # a comment on a sequence item
tags:
  - röstlinie
  - "quoted-tag"
prs: []
---

# Überprüfung der Randbedingungen

Body text with the things a naive serialiser eats: em dashes — ellipses …
mathematics (λ ≤ ½), Japanese (日本語), and a fenced block that must not be
reflowed:

```python
assert serialise(parse_text(text, "roundtrip.md"), text) == text  # ≡
```

Trailing blank lines below this one are also part of the bytes.

