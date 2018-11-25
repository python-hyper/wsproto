import pytest

from wsproto.events import Event


class SimpleEvent(Event):
    _fields = ["a", "b", "c", "d"]
    _defaults = {"c": None, "d": []}


def test_event_construction():
    event = SimpleEvent(a=1, b=0)
    assert event.a == 1
    assert event.b == 0
    assert event.c is None
    assert event.d == []


def test_event_construction_unknown():
    with pytest.raises(TypeError):
        SimpleEvent(a=1, b=0, e=2)


def test_event_construction_missing():
    with pytest.raises(TypeError):
        SimpleEvent(a=1)


def test_event_defaults():
    event = SimpleEvent(a=1, b=0, d=[2])
    event2 = SimpleEvent(a=1, b=0)
    assert event.d == [2]
    assert event2.d == []


def test_event_repr():
    event = SimpleEvent(a=1, b=0)
    assert repr(event) == "SimpleEvent(a=1, b=0, c=None, d=[])"


def test_event_equality():
    event = SimpleEvent(a=1, b=0)
    event2 = SimpleEvent(a=1, b=0)
    event3 = SimpleEvent(a=1, b=1)
    assert event == event2
    assert event != event3
