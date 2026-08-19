# FinVault v1 Legacy Study

This directory is the browseable record of the completed single-machine FinVault pilot.

The final executed version was v1.3. Its exact executable checkpoint is the Git tag `finvault-v1.3-final` at commit `1659c91`. Use that tag—not the current platform branch—to reproduce the original lock against the original source paths.

## Start here

- [Final report](FINAL_REPORT.md)
- [Presentation brief](PRESENTATION.md)
- [Final status](STATUS.md)
- [Supervisor dashboard](results/SUPERVISOR_DASHBOARD.svg)
- [Machine-readable results](results/results.json)

## Structure

| Path | Purpose |
|---|---|
| `PROTOCOL.md` | v1.3 prospective protocol |
| `lock/` | original lock manifest and checksums |
| `run/` | gate and pilot plans plus machine gate report |
| `results/` | aggregate metrics, report, CSV tables, and dashboard |
| `history/` | failed calibration attempts and evolving planning documents |
| `raw/` | ignored local hash-chained trace; never committed |

This directory preserves the original research provenance. The active platform begins at [`experiment.json`](../../experiment.json).
