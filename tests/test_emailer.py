import os
import smtplib
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from socdem_radar.emailer import send_digest
from socdem_radar.models import Paper, SourceReport


class _FlakySMTP:
    attempts = 0

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, username, password):
        return None

    def send_message(self, message, to_addrs):
        type(self).attempts += 1
        if type(self).attempts < 3:
            raise smtplib.SMTPServerDisconnected("temporary failure")


class EmailRetryTests(unittest.TestCase):
    def test_transient_smtp_failure_is_retried(self):
        _FlakySMTP.attempts = 0
        config = {
            "email": {
                "enabled": True,
                "retry_attempts": 3,
                "smtp": {
                    "host": "smtp.example.com",
                    "port": 465,
                    "use_ssl": True,
                    "username_env": "TEST_SMTP_USERNAME",
                    "password_env": "TEST_SMTP_PASSWORD",
                    "to_env": "TEST_EMAIL_TO",
                },
            }
        }
        environment = {
            "TEST_SMTP_USERNAME": "sender@example.com",
            "TEST_SMTP_PASSWORD": "secret",
            "TEST_EMAIL_TO": "reader@example.com",
        }
        with (
            patch.dict(os.environ, environment, clear=False),
            patch("socdem_radar.emailer.smtplib.SMTP_SSL", _FlakySMTP),
            patch("socdem_radar.emailer.time.sleep") as mocked_sleep,
        ):
            send_digest(
                [Paper(title="Test")],
                [SourceReport(name="test", ok=True)],
                datetime(2026, 7, 15, tzinfo=UTC),
                config,
            )
        self.assertEqual(_FlakySMTP.attempts, 3)
        self.assertEqual(mocked_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
