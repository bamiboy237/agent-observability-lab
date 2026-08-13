from app.domain.retrieval.chunking import DeterministicChunker, chunk_document
from app.domain.retrieval.contracts import SourceDocument
from app.domain.support.seed import POLICY_DOCUMENTS


def policy_document() -> SourceDocument:
    seed = POLICY_DOCUMENTS[0]
    return SourceDocument(
        document_id=seed["id"],
        slug=seed["slug"],
        version=seed["version"],
        title=seed["title"],
        content=seed["content"],
    )


def test_chunk_boundaries_ids_and_hashes_are_stable() -> None:
    document = policy_document()
    first = chunk_document(document, chunk_size=12, overlap=3)
    second = chunk_document(document, chunk_size=12, overlap=3)

    assert first == second
    assert [chunk.ordinal for chunk in first] == list(range(len(first)))
    assert all(len(chunk.text.split()) <= 12 for chunk in first)
    assert first[0].chunk_id != first[1].chunk_id


def test_chunk_overlap_is_explicit_and_invalid_settings_fail() -> None:
    document = SourceDocument(
        document_id=policy_document().document_id,
        slug="small",
        version="1",
        title="Small",
        content="one two three four five six",
    )
    chunks = DeterministicChunker(chunk_size=4, overlap=1).chunk(document)
    assert chunks[0].text == "one two three four"
    assert chunks[1].text == "four five six"

    for size, overlap in ((0, 0), (4, 4), (4, 5)):
        try:
            DeterministicChunker(chunk_size=size, overlap=overlap)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid chunk settings must fail")
