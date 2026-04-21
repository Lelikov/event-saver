"""Tests for ParticipantExtractor domain service."""

import uuid

from event_saver.domain.services.participant_extractor import ParticipantExtractor


class TestExtract:
    def setup_method(self) -> None:
        self.extractor = ParticipantExtractor()

    def test_extracts_both_participants(self) -> None:
        org_id = uuid.uuid4()
        client_id = uuid.uuid4()
        payload = {
            "normalized": {
                "participants": [
                    {"role": "organizer", "user_id": str(org_id)},
                    {"role": "client", "user_id": str(client_id)},
                ],
            },
        }

        organizer, client = self.extractor.extract(payload)

        assert organizer == org_id
        assert client == client_id

    def test_missing_normalized_returns_nones(self) -> None:
        organizer, client = self.extractor.extract({})

        assert organizer is None
        assert client is None

    def test_empty_participants_returns_nones(self) -> None:
        payload = {"normalized": {"participants": []}}

        organizer, client = self.extractor.extract(payload)

        assert organizer is None
        assert client is None

    def test_invalid_uuid_skipped(self) -> None:
        payload = {
            "normalized": {
                "participants": [
                    {"role": "organizer", "user_id": "not-a-uuid"},
                ],
            },
        }

        organizer, client = self.extractor.extract(payload)

        assert organizer is None
        assert client is None

    def test_non_dict_participants_skipped(self) -> None:
        payload = {
            "normalized": {
                "participants": ["not-a-dict", 42],
            },
        }

        organizer, client = self.extractor.extract(payload)

        assert organizer is None
        assert client is None

    def test_uuid_object_accepted(self) -> None:
        org_id = uuid.uuid4()
        payload = {
            "normalized": {
                "participants": [
                    {"role": "organizer", "user_id": org_id},
                ],
            },
        }

        organizer, _client = self.extractor.extract(payload)

        assert organizer == org_id
