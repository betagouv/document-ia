import logging

logger = logging.getLogger(__name__)


class QueueAutoScaler:
    """
    Control logic for the autoscaler.
    Decoupled from network calls for clean unit testing.
    """

    def __init__(
        self,
        min_workers: int = 1,
        max_workers: int = 5,
        thread_per_worker: int = 10,
        scale_up_cooldown: int = 120,
        scale_down_cooldown: int = 300,
    ):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.thread_per_worker = thread_per_worker
        self.scale_up_cooldown = scale_up_cooldown
        self.scale_down_cooldown = scale_down_cooldown

    def evaluate(
        self,
        current_time: float,
        last_scale_time: float,
        current_workers: int,
        queue_lag: int,
    ) -> tuple[str, int] | None:
        """
        Evaluate the current metrics and make a scaling decision.

        Args:
            current_time (float): Current epoch timestamp in seconds.
            last_scale_time (float): Epoch timestamp of the last scale action.
            current_workers (int): Current number of worker containers.
            queue_lag (int): Number of tasks backlogged in the queue.

        Returns:
            tuple[str, int] | None: A tuple ("scale_up"|"scale_down", target_count) or None.
        """
        max_capacity = current_workers * self.thread_per_worker
        time_since_last_action = current_time - last_scale_time

        # A) Scale-UP
        if queue_lag > max_capacity:
            if current_workers >= self.max_workers:
                logger.info(
                    "Lag exceeds capacity, but max workers limit reached (%d/%d).",
                    current_workers,
                    self.max_workers,
                )
                return None

            if time_since_last_action < self.scale_up_cooldown:
                logger.info(
                    "Scale-UP needed but blocked by cooldown (%ds/%ds).",
                    int(time_since_last_action),
                    self.scale_up_cooldown,
                )
                return None

            new_workers = current_workers + 1
            logger.info(
                "Surcharge detected (Lag=%d > Capacity=%d). Decided Scale-UP: %d -> %d.",
                queue_lag,
                max_capacity,
                current_workers,
                new_workers,
            )
            return ("scale_up", new_workers)

        # B) Scale-DOWN
        elif queue_lag == 0 and current_workers > self.min_workers:
            if time_since_last_action < self.scale_down_cooldown:
                logger.info(
                    "Scale-DOWN possible but blocked by cooldown (%ds/%ds).",
                    int(time_since_last_action),
                    self.scale_down_cooldown,
                )
                return None

            new_workers = current_workers - 1
            logger.info(
                "Underload detected (Queue is empty). Decided Scale-DOWN: %d -> %d.",
                current_workers,
                new_workers,
            )
            return ("scale_down", new_workers)

        return None
