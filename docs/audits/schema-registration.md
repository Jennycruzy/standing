# Product schema registration

## Result

Standing's two product schemas are registered in the configured Base SchemaRegistry. The registry was read before writing, and the final read returned both definitions directly from Base.

| Schema | UID | Registration transaction |
| --- | --- | --- |
| Condition definition | `0x23149c0983dd115883a770ef19de17b865bf571647a8fda25b465b05b676073a` | [Basescan](https://basescan.org/tx/0x742943c8723f64f956e05331700a3e7ebb8c9c67a408a1b3f6a6b441fa3dc1f4) |
| Observation | `0x8d1de28d570f01bfa1850def6d96fa9df60fdb08d528de9e7ad591a806d2e53e` | [Basescan](https://basescan.org/tx/0x0c9b5fd6f83ac4e3e63bcceabfd4ed613fea487b6b566172f5d85a77f092f74d) |

The condition-definition schema is:

`string conditionKey,string description,string valueType,string unit`

The observation schema is:

`string conditionKey,string value,uint64 effectiveFrom,string sourceUrl,uint8 sourceType,string note`

The observation schema is revocable for an erroneous or fraudulent observation. A later observation will reference an earlier one with `refUID`; it will not revoke it.

## Evidence

- Read-only preflight: `.preflight-venv/bin/python scripts/register_product_schemas.py` reported both schemas missing before the writes.
- Registration script: `scripts/register_product_schemas.py` reads first, writes only missing schemas with `--write`, and reads each result back at the mined block or retries the latest state while the RPC catches up.
- Final readback: the same command reported both schemas as `already_registered` with the UIDs above.
- Local verification: `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 44 tests passed.
- Type verification: `.preflight-venv/bin/python -m mypy --strict standing` — no issues found.

No vendor condition or vendor observation was published by this step.
