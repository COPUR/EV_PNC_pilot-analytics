# EV_PNC_pilot-analytics

Corridor pilot measurement: KPI-1 to KPI-7 jobs, control and treatment assignment rule, daily K1 count, price sheet, dashboards. Pseudonymous trip IDs only.

Part of the **EV_PNC** platform: a neutral eMSP integration layer for Turkey-first, Europe-ready Plug&Charge, navigation and payments. The platform is neither a CPO nor a payment institution.

> Plug in, charging starts, payment completes in the background.

## Scope

- KPI formulas from corridor-pilot/kpis.md as tested SQL/Python
- Daily K1 evidence count per channel (hub, bilateral OCPI, guest) before the 2026-11-09 checkpoint
- Baseline period then 50% treatment group; normal and peak reported separately
- Weekly direct-card price sheet and guest price gap (K8, CP-PRICE-003)
- Trace retention: cell level after 90 days (CP-KPI-004)

## Tech stack

Python 3.12, SQL, TimescaleDB, Grafana

## Packaging

- Published components: pilot-analytics
- Depends on: EV_PNC_ocpi-model, EV_PNC_payments, EV_PNC_planner, EV_PNC_pricing, EV_PNC_telemetry
- Depended on by: no repo
- Dependency rules: no cycles (ADP); depend towards more stable components (SDP); published `*-api` components hold abstractions, deployables hold concrete code (SAP). CI runs `tools/packaging_check.py --strict` from `EV_PNC_docs`.
- Owner: Data agent · Wave 1 (now, before the 2026-12-07 gate) · Visibility: public

## Proposed layout

```
kpi/
evidence/
dashboards/
```

## Related

- Plan: `repo-plan/v2/README.md` (project files); consent repos: `EV_PnC_Consent_*` (`repo-plan/consent/README.md`)
- Docs: [EV_PNC_docs](https://github.com/COPUR/EV_PNC_docs)

## Status

Scaffold only. Not production ready.

## License

Apache-2.0 (proposed)
