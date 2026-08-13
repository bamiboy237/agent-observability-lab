# User simulator

The persona simulator uses one generic command and grouped YAML catalogs; it no longer needs one launcher file per scenario.

```bash
uv run lab simulate list
uv run lab simulate validate
uv run lab simulate run <scenario-id> --yes
```

Simulation choices come from `simulations/*.yaml`. Safe test database profiles come from `config/simulation-environments.yaml`; secret values stay in environment variables.

The JSONL event log stores only allowlisted redacted fields. Use only `ENVIRONMENT=test` and a disposable database.
