# Daily K1 evidence count (card C-03, T-CP-16, CP-ACCESS-003)

K1 is the gate criterion "reachable EVSEs on the Istanbul-Bodrum corridor across all channels: at least 120, at least 45 of them DC". K1-H is the part reached through Hubject (ZES). The count is the evidence for both at the 9 Nov interim check and the 7 Dec gate.

```bash
uv run k1-count --index index.json --channels channels.csv --json-out k1.json --md-out k1.md
```

- `index.json`: output of `corridor-index` in EV_PNC_telemetry (card C-01).
- `channels.csv`: one row per EVSE and channel, columns `evse_uid, channel, status, hub, evidence_ref, evidence_date`. `channel` is `HUB`, `BILATERAL_OCPI` or `GUEST`; `hub` (`HUBJECT`, `GIREVE`, `E_CLEARING`) only on `HUB` rows; `status` is `confirmed`, `offered` or `claimed`. A `confirmed` row must name its evidence.
- Samples with fictional data are in `evidence/samples/`.

## What counts

- An EVSE counts toward K1 once, if the index marks it `k1_evidence` (user-listed stations never do) and at least one channel row for it is `confirmed`. It also counts in each channel it is confirmed on.
- `offered` and `claimed` rows are shown as potential, never as evidence.
- K1-H is the Hubject-confirmed share of the K1 total, reported separately. The threshold is still open (card G-01, proposal 20%); the report shows the share and says the threshold is open until `--k1h-min-share` is given.
- The report breaks counts down by channel, family and power class (AC, DC < 150 kW, DC >= 150 kW, unknown) as CP-ACCESS-003 requires, and lists what did not count and why.

## What "confirmed" should mean (proposal, needs the product owner's yes)

| Channel | Confirmed when |
|---|---|
| `HUB` | the EVSE is in the hub's EVSE data for our provider ID **and** our roaming agreement with that hub is signed |
| `BILATERAL_OCPI` | a signed agreement with the CPO **and** a completed credentials handshake that lists the EVSE in their Locations |
| `GUEST` | a test AD_HOC_USER session has started and stopped on that EVSE (or the CPO has confirmed in writing that it accepts ad-hoc tokens from us) |

Until agreements exist, almost nothing is `confirmed`, and the K1 count will say so. That is the honest reading for the interim check; the `offered` and `claimed` figures show how far it could go.

## Limits today

- **The corridor geometry is draft** (telemetry `v0`). The report prints a warning at the top while the index says so. Do not take the count to the gate until a routed geometry exists.
- The report is a command, not yet a scheduled job or a dashboard panel; both wait for the first environment and for the KPI jobs (T-CP-19).
- Plain Python, no database yet: the SQL/TimescaleDB layer comes with the KPI jobs.
