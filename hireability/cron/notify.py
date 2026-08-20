"""Lightweight notifications for cron runs (desktop, log, optional webhook)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from urllib import error, request

from hireability.config import CRON_LOG_PATH


def _append_log(message: str, log_path: Path = CRON_LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def _desktop_notify(title: str, message: str) -> bool:
    try:
        subprocess.run(
            ["notify-send", title, message],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    try:
        from plyer import notification

        notification.notify(title=title, message=message, timeout=10)
        return True
    except Exception:
        return False


def _webhook_notify(title: str, message: str, url: str) -> bool:
    payload = json.dumps({"title": title, "message": message, "content": f"**{title}**\n{message}"})
    req = request.Request(
        url,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15):
            return True
    except error.URLError:
        return False


def log_run(message: str, *, level: str = "info", log_path: Path = CRON_LOG_PATH) -> None:
    line = f"[{level.upper()}] {message}"
    _append_log(line, log_path)
    print(line)


def send_notification(
    title: str,
    message: str,
    *,
    level: str = "info",
    desktop: bool = True,
    log_path: Path = CRON_LOG_PATH,
) -> None:
    line = f"[{level.upper()}] {title}: {message}"
    _append_log(line, log_path)
    print(line)

    if desktop and os.environ.get("HIREABILITY_NOTIFY_DESKTOP", "1") != "0":
        _desktop_notify(title, message)

    webhook = os.environ.get("HIREABILITY_NOTIFY_WEBHOOK", "").strip()
    if webhook:
        _webhook_notify(title, message, webhook)
