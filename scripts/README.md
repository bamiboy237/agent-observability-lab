# User simulator scripts

Each `run_user_simulator_*.py` script starts one live Luna simulation. It prints the run ID, JSONL transcript path, and final report path **before** the first hosted-model request.

Start a run in the background and follow its safe JSONL events from another terminal:

```bash
uv run python scripts/run_user_simulator_disputes.py > /tmp/user-simulator.out 2>&1 &
SIM_PID=$!
sleep 1
tail -f "$(sed -n 's/^jsonl_path=//p' /tmp/user-simulator.out | head -n 1)" &
TAIL_PID=$!
wait "$SIM_PID"
kill "$TAIL_PID" 2>/dev/null || true
```

The JSONL log redacts conversation text. Use only `ENVIRONMENT=test` and the approved disposable test database.
