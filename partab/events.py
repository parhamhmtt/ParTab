from __future__ import annotations

from dataclasses import dataclass
import itertools
import queue
import threading
from typing import Iterable


@dataclass(frozen=True)
class Event:
    event_id: int
    name: str
    data: object


class EventBroker:

    def __init__(self):
        self._lock = threading.RLock()
        self._next_subscriber_id = itertools.count(1)
        self._next_event_id = itertools.count(1)
        self._subscribers: dict[int, tuple[queue.Queue, frozenset[str]]] = {}

    def subscribe(self, audiences: Iterable[str]):
        subscriber_id = next(self._next_subscriber_id)
        event_queue: queue.Queue[Event] = queue.Queue(maxsize=64)
        audience_set = frozenset(audiences)
        with self._lock:
            self._subscribers[subscriber_id] = (event_queue, audience_set)
        return subscriber_id, event_queue

    def unsubscribe(self, subscriber_id: int):
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def publish(self, audience: str, name: str, data=None):
        event = Event(next(self._next_event_id), name, {} if data is None else data)
        with self._lock:
            queues = [
                event_queue
                for event_queue, audiences in self._subscribers.values()
                if audience in audiences
            ]

        for event_queue in queues:
            try:
                event_queue.put_nowait(event)
            except queue.Full:
                try:
                    event_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    event_queue.put_nowait(event)
                except queue.Full:
                    pass


broker = EventBroker()
