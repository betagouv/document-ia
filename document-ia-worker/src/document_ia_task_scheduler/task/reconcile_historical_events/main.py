import argparse
import asyncio
import logging
import sys
from typing import Optional, Sequence

from document_ia_task_scheduler.task.reconcile_historical_events.job import (
    ReconcileHistoricalEventsJob,
    TargetType,
)

logger = logging.getLogger("reconcile_historical_events")


def parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rattrapage et re-purges des événements historiques DONE et ERROR",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--target",
        choices=["main", "analytics", "both"],
        default="both",
        help="Base de données cible pour la réconciliation",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Nombre d'enregistrements par lot",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.05,
        help="Pause en secondes entre chaque lot (ménage PostgreSQL et réplicas)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode simulation (aucun commit en base)",
    )
    return parser.parse_args(args)


async def async_main(args: argparse.Namespace) -> int:
    target: TargetType = args.target
    job = ReconcileHistoricalEventsJob(
        batch_size=args.batch_size,
        pause_seconds=args.pause,
        dry_run=args.dry_run,
    )
    stats = await job.run(target=target)
    total_errors = sum(s["errors"] for s in stats.values())
    return 1 if total_errors > 0 else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
