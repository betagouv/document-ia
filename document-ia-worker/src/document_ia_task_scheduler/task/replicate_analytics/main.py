import asyncio

from document_ia_task_scheduler.config.logging import setup_logging
from document_ia_task_scheduler.task.replicate_analytics.job import ReplicateAnalytics

if __name__ == "__main__":
    try:
        setup_logging()
        asyncio.run(ReplicateAnalytics().execute())
    except KeyboardInterrupt:
        pass
