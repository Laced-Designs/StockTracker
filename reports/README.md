# Saved research results

`EVIDENCE.md` contains the findings and limitations. `research-summary.json` contains market-level metrics. The complete 503-instrument report, including validation candidates, data fingerprints and per-regime results, is stored as `predictability.json.gz` to keep the repository compact.

Expand the complete report from the repository root:

```bash
python -c "import gzip,pathlib; p=pathlib.Path('reports/predictability.json'); p.write_bytes(gzip.decompress(p.with_suffix('.json.gz').read_bytes()))"
```

Downloaded datasets, embedded databases, job runtime state and `.env` remain local. Recreate them with the bootstrap, plan and research commands in `HISTORY.md`. Source access and current upstream snapshots can differ from this saved experiment; report fingerprints identify the original inputs.
