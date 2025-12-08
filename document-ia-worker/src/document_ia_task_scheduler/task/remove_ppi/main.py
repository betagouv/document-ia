import asyncio

from document_ia_task_scheduler.config.logging import setup_logging
from document_ia_task_scheduler.task.remove_ppi.job import RemovePPI

if __name__ == "__main__":
    try:
        setup_logging()
        asyncio.run(RemovePPI().execute())
    except KeyboardInterrupt:
        pass
