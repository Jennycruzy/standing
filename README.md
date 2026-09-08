# Standing

Standing remembers why a code decision was made and checks whether the facts it depended on still hold.

## Phase 1: memory

Sibyl Memory is the local store behind Standing. It is a database file on the machine, not a separate service.

- Decisions, conditions, and observer histories are written in [`standing/memory.py`](standing/memory.py#L41).
- A fresh process reads them through the same file at [`standing/memory.py`](standing/memory.py#L47).
- Decisions governing changed files are found by path at [`standing/memory.py`](standing/memory.py#L148).
- Archive and restore use the real Sibyl client plus its documented restore fallback at [`standing/memory.py`](standing/memory.py#L163).
- The memory-off test uses the same interface and starts with a new empty store at [`tests/test_memory.py`](tests/test_memory.py#L75).

The direct Python client is installed with:

```sh
uv pip install --python .preflight-venv/bin/python sibyl-memory-client==0.8.0
```

Run the Phase 1 tests with:

```sh
.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

The local memory database is ignored by Git. Secrets remain in the environment and are never written into memory records.

## Decision evaluation

The pure evaluator is [`standing/evaluator.py`](standing/evaluator.py#L101). It checks only the four supported rules, returns `STANDS`, `EXPIRED`, `UNKNOWN`, or `CONTESTED`, and produces a repeatable fingerprint for the result.

Only `EXPLICIT` and `CONFIRMED` conditions can block. An `INFERRED` or `EXTERNAL` condition remains visible as a note but cannot stop a change. The evaluator never reads files, calls a model, or writes to memory.

Run the complete test suite with:

```sh
.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

## Reviewer tools

The memory-backed reviewer tools are in [`standing/reviewer.py`](standing/reviewer.py#L59). They search approved paths, read decisions and current condition values, run the evaluator, read the boot journal, and write a checked standing change.

The write tool rejects a block when the evaluator returned `STANDS`, so the reviewer cannot invent a block. The real-storage tests are in [`tests/test_reviewer.py`](tests/test_reviewer.py#L12).

The complete test count is 32.

## Acceptance and observer history

The pure acceptance policy is [`standing/acceptance.py`](standing/acceptance.py#L176). Its thresholds live in [`config/policy.json`](config/policy.json), not in source. The configured policy requires a vendor-published observation, two independent observers with at least three confirmed readings and no contradictions, and human approval; otherwise the result is `CONTESTED`.

Observer selection reads the reliability records from memory and favors fewer contradictions, then more confirmed readings. A checked outcome updates the local record through [`standing/reviewer.py`](standing/reviewer.py#L137). The matching public reputation write is still separate work.
