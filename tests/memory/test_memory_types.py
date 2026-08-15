"""Contract tests for memory-owned records and operation outcomes."""

import math

import pytest

from voice_concierge.memory import (
    ExtractedMemoryMetadata,
    MemoryOperationOutcome,
    MemoryOperationStatus,
    MemoryRecord,
    MemoryRecordScope,
    MemorySearchResult,
    MemorySimilarityAdvisory,
    MemoryUpdate,
    MemoryWrite,
    VectorSearchResult,
    normalize_event_time,
    normalize_memory_strength,
)


def _record(**changes) -> MemoryRecord:
    values = {
        "id": 1,
        "content": "User prefers tea.",
        "layer": "profile",
        "memory_key": None,
        "revision": 1,
        "indexed_revision": 1,
        "deleted_at": None,
        "created_at": 1,
        "event_time": None,
        "last_accessed": None,
        "strength": 1,
        "person": None,
        "source_type": None,
        "topic": None,
    }
    values.update(changes)
    return MemoryRecord(**values)


def test_memory_record_rejects_index_revision_ahead_of_authority() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        _record(revision=2, indexed_revision=3)


def test_memory_write_rejects_storage_types_before_sql() -> None:
    with pytest.raises(ValueError, match="Event timestamp"):
        MemoryWrite(content="Appointment", layer="profile", event_time="tomorrow")


def test_memory_update_rejects_blank_content_before_sql() -> None:
    with pytest.raises(ValueError, match="content"):
        MemoryUpdate(content="  ")


@pytest.mark.parametrize("strength", (0, 11, True))
def test_memory_write_enforces_documented_strength_range(strength: object) -> None:
    with pytest.raises(ValueError, match="1 to 10"):
        MemoryWrite(content="Preference", layer="profile", strength=strength)


def test_search_result_keeps_distance_out_of_authoritative_record() -> None:
    record = _record()
    result = MemorySearchResult(memory=record, distance=0.25)

    assert result.memory is record
    assert result.distance == 0.25
    assert not hasattr(record, "distance")


@pytest.mark.parametrize("retention", (-0.1, 1.1, math.nan, math.inf, True))
def test_search_result_rejects_invalid_retention_score(retention: object) -> None:
    with pytest.raises(ValueError, match="finite number between"):
        MemorySearchResult(
            memory=_record(),
            distance=0.25,
            retention_score=retention,
        )


def test_memory_scope_treats_none_as_an_exact_value() -> None:
    scope = MemoryRecordScope(layer="profile", topic=None)

    assert scope.contains(_record(layer="profile", topic=None)) is True
    assert scope.contains(_record(layer="profile", topic="preference")) is False


@pytest.mark.parametrize("distance", (-0.1, math.nan, math.inf))
def test_vector_result_rejects_invalid_distance(distance: float) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        VectorSearchResult(memory_id=1, distance=distance)


@pytest.mark.parametrize(
    "status",
    (
        MemoryOperationStatus.STORED_SUCCESSFULLY,
        MemoryOperationStatus.STORED_PENDING_INDEX,
        MemoryOperationStatus.UPDATED_SUCCESSFULLY,
        MemoryOperationStatus.UPDATED_PENDING_INDEX,
        MemoryOperationStatus.NO_CHANGES,
        MemoryOperationStatus.DELETED_SUCCESSFULLY,
        MemoryOperationStatus.DELETED_PENDING_INDEX_CLEANUP,
    ),
)
def test_success_is_derived_from_operation_status(
    status: MemoryOperationStatus,
) -> None:
    assert MemoryOperationOutcome(status).succeeded is True


def test_failure_status_cannot_disagree_with_success_flag() -> None:
    outcome = MemoryOperationOutcome(
        MemoryOperationStatus.STORAGE_ERROR,
        detail="database unavailable",
    )

    assert outcome.succeeded is False
    assert outcome.reason == "storage_error: database unavailable"


def test_operation_outcome_carries_typed_similarity_advisories() -> None:
    advisory = MemorySimilarityAdvisory(memory_id=4, distance=0.05)
    outcome = MemoryOperationOutcome(
        MemoryOperationStatus.STORED_SUCCESSFULLY,
        memory_id=5,
        similarity_advisories=(advisory,),
    )

    assert outcome.succeeded is True
    assert outcome.similarity_advisories == (advisory,)


def test_operation_outcome_rejects_untyped_similarity_advisories() -> None:
    with pytest.raises(TypeError, match="MemorySimilarityAdvisory"):
        MemoryOperationOutcome(
            MemoryOperationStatus.STORED_SUCCESSFULLY,
            similarity_advisories=({"memory_id": 4, "distance": 0.05},),
        )


def test_operation_outcome_requires_enum_status() -> None:
    with pytest.raises(TypeError, match="MemoryOperationStatus"):
        MemoryOperationOutcome("stored_successfully")


def test_iso_event_time_is_normalized_to_utc_timestamp() -> None:
    assert normalize_event_time("1970-01-01T00:01:00Z") == 60
    assert normalize_event_time("not a date") is None


def test_memory_strength_normalization_bounds_model_values() -> None:
    assert normalize_memory_strength(0) == 1
    assert normalize_memory_strength(11) == 10
    assert normalize_memory_strength("high", default=5) == 5


def test_extracted_metadata_normalizes_untrusted_model_values() -> None:
    metadata = ExtractedMemoryMetadata.from_value(
        {
            "person": " Alice ",
            "source_type": 4,
            "event_time": "1970-01-01T00:01:00Z",
            "strength": 100,
        }
    )

    assert metadata == ExtractedMemoryMetadata(
        person="Alice",
        source_type=None,
        event_time=60,
        strength=10,
    )


def test_extracted_metadata_rejects_non_mapping_payload_as_a_unit() -> None:
    assert ExtractedMemoryMetadata.from_value(["not", "metadata"]) == (
        ExtractedMemoryMetadata()
    )
