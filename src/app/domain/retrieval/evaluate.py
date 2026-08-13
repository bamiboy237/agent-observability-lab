"""Versioned retrieval evaluation command and artifact writer."""

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.domain.retrieval.contracts import Retriever
from app.domain.retrieval.metrics import RetrievalExample, evaluate_results

DATASET_VERSION = "retrieval_eval_v1"
CORPUS_VERSION = "policy-v1"
# This floor is checked into the evaluation contract after measuring the seeded
# corpus.  A later corpus or retriever must change the dataset/artifact version.
ACCEPTED_RECALL_AT_5_FLOOR = 0.80


def load_dataset(path: Path) -> list[RetrievalExample]:
    """Load a JSONL retrieval dataset with strict, stable fields."""
    examples: list[RetrievalExample] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            examples.append(
                RetrievalExample(
                    case_id=str(value["case_id"]),
                    query=str(value["query"]),
                    expected_chunk_ids=tuple(str(item) for item in value["expected_chunk_ids"]),
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid retrieval dataset line {line_number}") from error
    if not examples:
        raise ValueError("retrieval dataset is empty")
    return examples


async def evaluate_retriever(
    retriever: Retriever,
    examples: Sequence[RetrievalExample],
    *,
    k: int = 5,
) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
    """Evaluate one retriever and return metrics plus failed queries."""
    results = [await retriever.search(example.query, k) for example in examples]
    metrics = evaluate_results(examples, results, k=k)
    failures = [
        {
            "case_id": example.case_id,
            "query": example.query,
            "expected_chunk_ids": list(example.expected_chunk_ids),
            "returned_chunk_ids": [str(hit.chunk_id) for hit in hits],
        }
        for example, hits in zip(examples, results, strict=True)
        if not {str(hit.chunk_id) for hit in hits[:k]} & set(example.expected_chunk_ids)
    ]
    return metrics, failures


def write_artifact(
    path: Path,
    *,
    metrics: dict[str, float | int],
    failures: list[dict[str, Any]],
    dataset_version: str = DATASET_VERSION,
    corpus_version: str = CORPUS_VERSION,
    retriever_version: str = "keyword-vector-rrf-v1",
) -> None:
    """Write a reviewable, versioned evaluation artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "dataset_version": dataset_version,
                "corpus_version": corpus_version,
                "retriever_version": retriever_version,
                "metrics": metrics,
                "failed_queries": failures,
                "accepted_floor": {"recall_at_5": ACCEPTED_RECALL_AT_5_FLOOR},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> None:
    """Run the evaluation against an application-configured retriever.

    The command keeps construction intentionally small.  Deployments can
    import :func:`evaluate_retriever` with their chosen provider and retriever;
    this module owns dataset loading and artifact shape.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DATASET_VERSION)
    parser.add_argument("--path", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("artifacts/retrieval-eval-v1.json"))
    arguments = parser.parse_args()
    dataset_path = arguments.path or Path("tests/fixtures") / f"{arguments.dataset}.jsonl"
    examples = load_dataset(dataset_path)

    async def run() -> tuple[dict[str, float | int], list[dict[str, Any]]]:
        from app.db import get_session_factory
        from app.domain.retrieval.storage import KeywordRetriever

        async with get_session_factory()() as session:
            return await evaluate_retriever(KeywordRetriever(session), examples)

    metrics, failures = asyncio.run(run())
    write_artifact(arguments.output, metrics=metrics, failures=failures)
    recall = float(metrics.get("recall_at_5", 0.0))
    if recall < ACCEPTED_RECALL_AT_5_FLOOR:
        raise SystemExit(f"retrieval floor failed: recall_at_5={recall:.3f}")


if __name__ == "__main__":
    main()
