"""Domain model for participants (organizers and clients)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Participant:
    """Participant value object.

    Represents a user (organizer or client) extracted from event payload.
    Immutable and hashable for use in sets/dicts.
    """

    email: str
    role: str | None = None
    time_zone: str | None = None

    def merge_with(self, other: Participant) -> Participant:
        """Merge this participant with another, preferring non-None values from other.

        Used for updating participant data when new information arrives.
        """
        if self.email != other.email:
            msg = f"Cannot merge participants with different emails: {self.email} vs {other.email}"
            raise ValueError(msg)

        return Participant(
            email=self.email,
            role=other.role if other.role is not None else self.role,
            time_zone=other.time_zone if other.time_zone is not None else self.time_zone,
        )
