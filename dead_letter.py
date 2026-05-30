import json
import logging
from datetime import datetime
from typing import Dict, List
import config

logger = logging.getLogger(__name__)

class DeadLetterQueue:
    """JSONL-based dead letter queue for failed email processing."""

    def __init__(self, filepath: str = None):
        self.filepath = filepath or config.DEAD_LETTER_FILE

    def add(self, email_id: str, subject: str, sender: str, reason: str, llm_output: Dict = None):
        """Add a failed email to the dead letter queue."""
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "email_id": email_id,
            "subject": subject,
            "sender": sender,
            "reason": reason,
            "llm_output": llm_output,
        }

        try:
            with open(self.filepath, "a") as f:
                f.write(json.dumps(record) + "\n")
            logger.info(f"Added {email_id} to dead letter queue: {reason}")
        except Exception as e:
            logger.error(f"Failed to write to dead letter queue: {e}")

    def read_all(self) -> List[Dict]:
        """Read all entries from dead letter queue."""
        entries = []
        try:
            with open(self.filepath, "r") as f:
                for line in f:
                    if line.strip():
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        return entries

    def clear(self):
        """Clear the dead letter queue."""
        try:
            with open(self.filepath, "w") as f:
                pass
            logger.info("Dead letter queue cleared")
        except Exception as e:
            logger.error(f"Failed to clear dead letter queue: {e}")

    def stats(self) -> Dict:
        """Get stats on dead letter queue."""
        entries = self.read_all()
        reasons = {}
        for entry in entries:
            reason = entry.get("reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1

        return {
            "total": len(entries),
            "by_reason": reasons,
        }
