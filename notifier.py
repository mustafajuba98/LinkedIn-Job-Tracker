import logging

logger = logging.getLogger(__name__)


def notify_new_job(job):
    """Send a native desktop notification for a newly discovered job."""
    title = "New LinkedIn Job"
    body = "\n".join(
        part
        for part in [
            getattr(job, "title", None) or "New job",
            getattr(job, "company", None) or "",
            getattr(job, "location", None) or "",
            "",
            "Click/Open the application to view it.",
        ]
        if part is not None
    )

    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=body.strip(),
            app_name="LinkedIn Job Tracker",
            timeout=10,
        )
    except Exception:
        logger.exception("Notification error")
