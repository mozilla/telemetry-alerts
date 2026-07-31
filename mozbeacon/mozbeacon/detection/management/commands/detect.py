import logging
import traceback

from django.core.management.base import BaseCommand

from mozbeacon.detection.detector import Detector
from mozbeacon.detection.utils import DESKTOP, MOBILE

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """The nightly worker.

    Was Treeherder's perf_sheriff command, which ran backfilling and then called
    telemetry_alert() inside a try/except. Backfilling stayed behind, and Cloud
    Scheduler owns the schedule, so what's left is the detection run itself.
    """

    help = "Run telemetry change detection and alerting."

    def add_arguments(self, parser):
        parser.add_argument(
            "--probe-filter",
            help=(
                "Only run detection for this probe (dots replaced with underscores, "
                "e.g. 'performance_pageload_fcp'). Defaults to all probes."
            ),
        )
        parser.add_argument(
            "--platform-filter",
            choices=[DESKTOP, MOBILE],
            help=f"Only run probes for this platform type ('{DESKTOP}' or '{MOBILE}').",
        )
        parser.add_argument(
            "--label-filter",
            help=(
                "Only run detection for this label of a labeled probe. Ignored for "
                "probes that aren't labeled."
            ),
        )
        parser.add_argument(
            "--max-detections",
            type=int,
            help="Turn at most this many detections per platform into alerts.",
        )

    def handle(self, *args, **options):
        try:
            Detector().telemetry_alert(
                probe_filter=options["probe_filter"],
                max_detections=options["max_detections"],
                platform_filter=options["platform_filter"],
                label_filter=options["label_filter"],
            )
        except Exception:
            # Let this fail the run. Treeherder swallowed it because telemetry alerting
            # was a passenger on the sheriffing job. Here it is the job, and a swallowed
            # exception is a night that reports success while producing nothing.
            logger.error(f"Telemetry alerting failed\n{traceback.format_exc()}")
            raise
