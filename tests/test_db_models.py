"""Guard tests: Alembic ORM metadata must match the migrated schema.

The ORM exists only for Alembic autogenerate; if it drifts from the
migration chain, autogenerate emits destructive drops.
"""

from event_saver.db import models  # noqa: F401
from event_saver.db.base import Base


_EXPECTED_TABLES = {
    "events",
    "bookings",
    "booking_organizer_history",
    "booking_meeting_links",
    "booking_email_notifications",
    "booking_telegram_notifications",
    "booking_email_status_history",
    "booking_chat_events",
    "booking_video_events",
    "booking_lifecycle_events",
}


class TestMetadataCoverage:
    def test_all_owned_tables_are_modeled(self) -> None:
        assert set(Base.metadata.tables) == _EXPECTED_TABLES

    def test_events_has_tracing_and_idempotency_columns(self) -> None:
        columns = set(Base.metadata.tables["events"].columns.keys())

        assert {"idempotency_key", "trace_id", "span_id", "dataschema"} <= columns

    def test_events_has_no_legacy_dedup_index(self) -> None:
        index_names = {idx.name for idx in Base.metadata.tables["events"].indexes}

        assert "uq_events_booking_id_event_type_source_hash" not in index_names
        assert "idx_events_idempotency" in index_names
        assert "idx_events_trace_id" in index_names

    def test_idempotency_index_is_partial_unique(self) -> None:
        index = next(idx for idx in Base.metadata.tables["events"].indexes if idx.name == "idx_events_idempotency")

        assert index.unique is True
        assert "idempotency_key IS NOT NULL" in str(index.dialect_options["postgresql"]["where"])

    def test_booking_lifecycle_events_matches_migration(self) -> None:
        table = Base.metadata.tables["booking_lifecycle_events"]
        columns = set(table.columns.keys())

        assert columns == {
            "id",
            "booking_ref_id",
            "raw_event_id",
            "action",
            "organizer_user_id",
            "client_user_id",
            "details",
            "occurred_at",
            "created_at",
        }
        fk_targets = {fk.target_fullname for fk in table.foreign_keys}
        assert fk_targets == {"bookings.id", "events.event_id"}
