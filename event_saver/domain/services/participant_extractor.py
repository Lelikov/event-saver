"""Domain service for extracting participants from event payloads."""

from typing import Any

from event_saver.domain.models.participant import Participant


class ParticipantExtractor:
    """Extract participant information from event payloads.

    Different event sources have different payload structures.
    This service knows how to extract participant data from each.
    """

    def extract_from_booking_event(self, payload: dict[str, Any]) -> list[Participant]:
        """Extract participants from booking events.

        Booking events have a 'users' array with role, email, timezone.
        """
        participants: list[Participant] = []

        users = payload.get("users")
        if not isinstance(users, list):
            return participants

        for user in users:
            if not isinstance(user, dict):
                continue

            email = user.get("email")
            if not isinstance(email, str) or not email:
                continue

            role = user.get("role")
            time_zone = user.get("time_zone")

            participants.append(
                Participant(
                    email=email,
                    role=role if isinstance(role, str) else None,
                    time_zone=time_zone if isinstance(time_zone, str) else None,
                )
            )

        return participants

    def extract_from_unisender_event(self, payload: dict[str, Any]) -> list[Participant]:
        """Extract participant from Unisender events.

        Unisender events have event_data.email.
        """
        event_data = payload.get("event_data")
        if not isinstance(event_data, dict):
            return []

        email = event_data.get("email")
        if not isinstance(email, str) or not email:
            return []

        return [Participant(email=email)]

    def extract_from_getstream_event(
        self,
        payload: dict[str, Any],
        *,
        decode_user_id: callable,
    ) -> list[Participant]:
        """Extract participant from GetStream events.

        GetStream events have user.id which needs to be decoded.
        """
        user = payload.get("user")
        if not isinstance(user, dict):
            return []

        encoded_user_id = user.get("id")
        if not isinstance(encoded_user_id, str) or not encoded_user_id:
            return []

        try:
            email = decode_user_id(encoded_user_id)
            if not isinstance(email, str) or not email:
                return []
            return [Participant(email=email)]
        except Exception:
            return []

    def extract_from_jitsi_event(self, payload: dict[str, Any]) -> list[Participant]:
        """Extract participant from Jitsi events.

        Jitsi events have context.user with email and role.
        """
        context = payload.get("context")
        if not isinstance(context, dict):
            return []

        user = context.get("user")
        if not isinstance(user, dict):
            return []

        email = user.get("email")
        if not isinstance(email, str) or not email:
            return []

        role = user.get("role")

        return [
            Participant(
                email=email,
                role=role if isinstance(role, str) else None,
            )
        ]
