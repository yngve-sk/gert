import asyncio
from collections import defaultdict

from pydantic import BaseModel


class RealizationStatus(BaseModel):
    """Status of a specific realization execution."""

    realization_id: int
    iteration: int
    status: str
    responses_emitted: int = 0
    last_response_name: str | None = None
    last_response_value: str | None = None


class MonitoringService:
    """Service to track and distribute experiment execution status."""

    def __init__(self) -> None:
        # experiment_id -> realization_id -> RealizationStatus
        self._states: dict[str, dict[int, RealizationStatus]] = defaultdict(dict)
        self._listeners: dict[str, list[asyncio.Queue[RealizationStatus]]] = (
            defaultdict(list)
        )

    def update_status(
        self,
        experiment_id: str,
        realization_id: int,
        iteration: int,
        status: str,
    ) -> None:
        """Update the status of a realization and notify listeners."""
        state = self._states[experiment_id].get(realization_id)
        if state:
            state.status = status
            state.iteration = iteration
        else:
            state = RealizationStatus(
                realization_id=realization_id,
                iteration=iteration,
                status=status,
            )
            self._states[experiment_id][realization_id] = state

        # Notify WebSocket listeners
        for queue in self._listeners[experiment_id]:
            queue.put_nowait(state)

    def increment_responses(
        self,
        experiment_id: str,
        realization_id: int,
        last_response_name: str | None = None,
        last_response_value: str | None = None,
    ) -> None:
        """Increment the response count for a realization."""
        state = self._states[experiment_id].get(realization_id)
        if state:
            state.responses_emitted += 1
            if last_response_name is not None:
                state.last_response_name = last_response_name
            if last_response_value is not None:
                state.last_response_value = last_response_value
            for queue in self._listeners[experiment_id]:
                queue.put_nowait(state)

    def get_experiment_status(self, experiment_id: str) -> list[RealizationStatus]:
        """Get the current status of all realizations for an experiment."""
        return list(self._states[experiment_id].values())

    async def subscribe(self, experiment_id: str) -> asyncio.Queue[RealizationStatus]:
        """Subscribe to status updates for an experiment."""
        queue: asyncio.Queue[RealizationStatus] = asyncio.Queue()
        self._listeners[experiment_id].append(queue)
        return queue

    def unsubscribe(
        self,
        experiment_id: str,
        queue: asyncio.Queue[RealizationStatus],
    ) -> None:
        """Unsubscribe from status updates."""
        if queue in self._listeners[experiment_id]:
            self._listeners[experiment_id].remove(queue)


# Singleton instance
monitoring_service = MonitoringService()
