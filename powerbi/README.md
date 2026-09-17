# Power BI

*Placeholder — Phase 4 builds the semantic model and the report.*

## What is here today

An empty PBIP scaffold, committed so the layout and the format choice are fixed before any
modelling starts:

| Path | Contents |
|---|---|
| `LPLens.pbip` | Project entry point, `version: 1.0`, pointing at `LPLens.Report` |
| `LPLens.SemanticModel/` | TMDL. `database.tmdl`, an empty `model.tmdl`, and the `en-US` culture. Zero tables, zero relationships, zero measures. |
| `LPLens.Report/` | PBIR folder format (`definition.pbir` version 4.0). One blank page, `Overview`. Zero visuals. |

## Format choice

The report half is **PBIR** (`definition/` folder of per-page and per-visual JSON), not the legacy
single-file `report.json`. The audited predecessor project used legacy `report.json` deliberately,
because it was generator-friendly; see `docs/AUDIT.md` section 3. PBIR is chosen here instead so
that a review diff shows one changed visual rather than one changed 66 KB file.

## Status

**Designed, not deployed.** These files were written by hand to the documented PBIP, TMDL and PBIR
schemas. They have **not** been opened in Power BI Desktop, so the scaffold is unvalidated against
the tool. Phase 4 opens it, and any correction the tool demands lands in that phase's PR.

No Power BI Service workspace is in use, so there is no published report link.
