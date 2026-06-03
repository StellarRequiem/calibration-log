"""calibration-log — a public, hash-chained track record of predictions.

Pre-register a prediction with a probability and a resolution date; resolve it
later; the log scores how well-calibrated you actually are (Brier score +
calibration table). Append-only and hash-linked, so the record can't be quietly
rewritten. The externalized form of "no belief without verification" — turned on
your own judgment.
"""
from .audit import AuditChain
from .log import CalibrationLog

__version__ = "0.1.0"
__all__ = ["CalibrationLog", "AuditChain"]
