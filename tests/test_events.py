"""EventLog: Kausal-Invarianten und ID-Vergabe (history-machine.md §3-4)."""

from __future__ import annotations

import pytest
from worldsim.events import EventDraft, EventKind, EventLog


def _draft(causes: tuple[int, ...] = ()) -> EventDraft:
    return EventDraft(year=0, kind=EventKind.GRUENDUNG, subjects=(1,), causes=causes)


def test_append_assigns_monotonic_ids() -> None:
    log = EventLog()
    assert log.append(_draft()) == 0
    assert log.append(_draft()) == 1
    assert [e.id for e in log] == [0, 1]


def test_causes_must_reference_earlier_events() -> None:
    log = EventLog()
    log.append(_draft())  # id 0

    # Gueltig: verweist auf das fruehere Event 0.
    assert log.append(_draft(causes=(0,))) == 1

    # Ungueltig: Vorwaerts-/Selbstreferenz.
    with pytest.raises(ValueError):
        log.append(_draft(causes=(99,)))


def test_indices_query_by_kind_and_year() -> None:
    log = EventLog()
    log.append(EventDraft(year=3, kind=EventKind.EXPANSION, subjects=(7,)))
    log.append(EventDraft(year=3, kind=EventKind.HUNGERSNOT, subjects=(7,)))

    assert len(log.by_year(3)) == 2
    assert len(log.by_kind(EventKind.EXPANSION)) == 1
    assert {e.id for e in log.by_subject(7)} == {0, 1}
