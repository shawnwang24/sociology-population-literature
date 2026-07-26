from __future__ import annotations

import logging
import os
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from .models import HealthStatus, Paper, SourceReport
from .render import render_html, render_markdown


LOGGER = logging.getLogger(__name__)


class EmailConfigError(ValueError):
    pass


def _env(name: str, required: bool = True) -> str:
    value = os.getenv(name, "").strip()
    if required and not value:
        raise EmailConfigError(f"缺少环境变量：{name}")
    return value


def send_digest(
    papers: list[Paper],
    source_reports: list[SourceReport],
    generated_at: datetime,
    config: dict[str, Any],
    health_status: HealthStatus | None = None,
) -> None:
    email_config = config.get("email") or {}
    if not email_config.get("enabled", True):
        return
    smtp_config = email_config.get("smtp") or {}
    username = _env(str(smtp_config.get("username_env", "SMTP_USERNAME")))
    password = _env(str(smtp_config.get("password_env", "SMTP_PASSWORD")))
    sender = _env(str(smtp_config.get("from_env", "SMTP_FROM")), required=False) or username
    recipient_raw = _env(str(smtp_config.get("to_env", "EMAIL_TO")))
    recipients = [value.strip() for value in recipient_raw.replace(";", ",").split(",") if value.strip()]
    if not recipients:
        raise EmailConfigError("收件人列表为空")

    host = str(smtp_config.get("host", "smtp.gmail.com"))
    port = int(smtp_config.get("port", 587))
    use_ssl = bool(smtp_config.get("use_ssl", False))
    use_starttls = bool(smtp_config.get("use_starttls", not use_ssl))
    sender_name = str(email_config.get("sender_name", "社会学与人口学文献雷达"))
    prefix = str(email_config.get("subject_prefix", "[文献雷达]"))
    status_label = ""
    if health_status and health_status.errors:
        status_label = "⚠️ 来源健康异常｜"
    elif health_status and (health_status.warnings or health_status.failed_sources):
        status_label = "⚠️ 来源警告｜"
    elif not papers:
        status_label = "运行成功｜"
    subject = f"{prefix} {status_label}{generated_at.date().isoformat()}｜{len(papers)} 篇新论文"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, sender))
    message["To"] = ", ".join(recipients)
    message.set_content(render_markdown(papers, source_reports, generated_at, config, health_status))
    message.add_alternative(
        render_html(papers, source_reports, generated_at, config, health_status),
        subtype="html",
    )

    context = ssl.create_default_context()
    attempts = max(1, int(email_config.get("retry_attempts", 3)))
    for attempt in range(1, attempts + 1):
        try:
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as client:
                    client.login(username, password)
                    client.send_message(message, to_addrs=recipients)
            else:
                with smtplib.SMTP(host, port, timeout=30) as client:
                    client.ehlo()
                    if use_starttls:
                        client.starttls(context=context)
                        client.ehlo()
                    client.login(username, password)
                    client.send_message(message, to_addrs=recipients)
            return
        except smtplib.SMTPAuthenticationError:
            raise
        except (smtplib.SMTPException, OSError) as exc:
            if attempt >= attempts:
                raise
            delay = min(10, 2 ** (attempt - 1))
            LOGGER.warning("SMTP 发送失败，第 %s/%s 次：%s；%s 秒后重试", attempt, attempts, exc, delay)
            time.sleep(delay)


def send_test(config: dict[str, Any], now: datetime) -> None:
    sample = Paper(
        title="文献雷达测试邮件：如果你看到这封邮件，SMTP 配置已经成功",
        authors=["SocDem Literature Radar"],
        journal="系统测试",
        published_at=now.date().isoformat(),
        abstract="这是一条本地生成的测试记录，不对应真实论文。",
        score=9.9,
        matched_groups=["测试"],
        matched_terms=["SMTP"],
    )
    send_digest([sample], [SourceReport(name="SMTP test", ok=True, paper_count=1)], now, config)
