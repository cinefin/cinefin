"""Seat occupancy is per screening; unscheduled tickets form their own pool."""

from datetime import timedelta

import pytest

from cinefin.api.exceptions import ValidationError
from cinefin.api.models import Settings, TicketIssue
from cinefin.api.services import ticket_service

from .factories import ProgrammeFactory, ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db


def _sell(programme, seat, schedule=None):
    TicketIssue.issue(kind=TicketIssue.KIND_PROGRAMME, title="x", seat=seat, programme=programme, schedule=schedule)


@pytest.fixture
def house():
    Settings.set("tickets.total_rows", 1)
    Settings.set("tickets.seats_per_row", 2)
    programme = ProgrammeFactory()
    first = ProgrammeScheduleFactory(programme=programme)
    second = ProgrammeScheduleFactory(programme=programme, start_time=first.start_time + timedelta(days=1))
    _sell(programme, "A1", first)
    _sell(programme, "A2", first)
    return programme, first, second


def test_a_full_screening_leaves_the_others_free(house):
    programme, first, second = house
    with pytest.raises(ValidationError):
        ticket_service.next_available_seat(programme, first)
    assert ticket_service.next_available_seat(programme, second) in {"A1", "A2"}
    assert ticket_service.next_available_seat(programme) in {"A1", "A2"}


def test_unscheduled_tickets_only_fill_the_unscheduled_pool(house):
    programme, _, second = house
    _sell(programme, "A1")
    assert ticket_service.occupied_seats(programme) == {"A1"}
    assert ticket_service.occupied_seats(programme, second) == set()


def test_seat_map_and_issued_list_follow_the_screening(client, house):
    programme, first, second = house

    def get(path, **query):
        return client.get(f"/api/v2/tickets/{path}", {"programme_id": programme.id, **query}).json()["data"]

    assert get("seats", schedule_id=first.id)["occupied"] == ["A1", "A2"]
    assert get("seats", schedule_id=second.id)["occupied"] == []
    assert get("seats")["occupied"] == []
    assert get("issued")["count"] == 2
    assert get("issued", schedule_id=first.id)["count"] == 2
    assert get("issued", schedule_id=second.id)["count"] == 0
