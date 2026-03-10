import logging
import logging.handlers
import os
from pythonjsonlogger import jsonlogger

# Architecture: Compliance logs are split into two streams based on German/EU legal retention requirements.
#
#   audit-compliance.log   — auth events, consents, account/chat deletions, data access (2-year retention)
#                            Legal basis: GDPR accountability + BSI recommendation (§34 BDSG)
#
#   financial-compliance.log — financial transactions and refund requests (10-year retention)
#                               Legal basis: AO §147, HGB §257 (German commercial/tax law)
#
# Both streams are:
#   1. Written to host-filesystem log files (bind-mounted, survives docker volume wipes)
#   2. Ingested into OpenObserve for real-time querying (stream-level retention overrides set on startup)
#   3. Backed up nightly to S3 Hetzner (see compliance_log_backup_task in main.py)
#
# Docs: docs/architecture/ (TODO: add dedicated compliance-logging.md)


class _ComplianceJsonFormatter(jsonlogger.JsonFormatter):
    """Ensures user_ids are not redacted and log entries are properly formatted as flat JSON."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)

        # If the message is already a dict (structured log entry), flatten it into the record
        if isinstance(record.msg, dict):
            for key, value in record.msg.items():
                log_record[key] = value

        if 'timestamp' not in log_record:
            log_record['timestamp'] = self.formatTime(record, self.datefmt)

        log_record['level'] = record.levelname


def _build_logger(name: str, log_file: str) -> logging.Logger:
    """
    Build a compliance logger that writes JSON to a time-rotating file.

    Args:
        name:     Logger name (e.g. 'compliance.audit' or 'compliance.financial')
        log_file: Absolute path to the log file (e.g. '/app/logs/audit-compliance.log')
    """
    logger = logging.getLogger(name)

    # Remove any handlers added by a previous call (e.g. during tests or hot reload)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    log_dir = os.path.dirname(log_file)
    os.makedirs(log_dir, exist_ok=True)

    # Time-based rotation — daily by default, keep ALL rotated files (backupCount=0).
    # Manual deletion / S3 archiving is the only permitted removal mechanism.
    # Override via env: COMPLIANCE_LOG_WHEN, COMPLIANCE_LOG_INTERVAL, COMPLIANCE_LOG_BACKUP_COUNT
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file,
        when=os.getenv("COMPLIANCE_LOG_WHEN", "D"),
        interval=int(os.getenv("COMPLIANCE_LOG_INTERVAL", "1")),
        encoding="utf-8",
        # CRITICAL: 0 = never auto-delete. Manual/S3-backed archiving handles eventual cleanup.
        backupCount=int(os.getenv("COMPLIANCE_LOG_BACKUP_COUNT", "0")),
    )

    formatter = _ComplianceJsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    file_handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    # Prevent double-logging to root (setup_logging.py already captures everything else)
    logger.propagate = False

    # Also emit to stdout in development so logs show up in `docker compose logs`
    if os.getenv("ENVIRONMENT", "development") == "development":
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def setup_compliance_logging():
    """
    Configure both compliance loggers and return them as a tuple.

    Returns:
        (audit_logger, financial_logger)

        audit_logger     — 2-year retention stream (auth, consents, deletions)
        financial_logger — 10-year retention stream (financial transactions, refunds)
    """
    log_dir = os.getenv("LOG_DIR", "/app/logs")

    audit_logger = _build_logger(
        name="compliance.audit",
        log_file=os.path.join(log_dir, "audit-compliance.log"),
    )
    financial_logger = _build_logger(
        name="compliance.financial",
        log_file=os.path.join(log_dir, "financial-compliance.log"),
    )

    return audit_logger, financial_logger
