from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


APP_VERSION = "v1.0.0"
APP_VERSION_LABEL = "Web Edition V1.0"
GITHUB_RELEASES_URL = "https://api.github.com/repos/Plungis/MAM-Spender-Web-Edition/releases/latest"
GITHUB_RELEASES_PAGE = "https://github.com/Plungis/MAM-Spender-Web-Edition/releases"
VERSION_CHECK_SECONDS = 60 * 60
HOST = os.environ.get("MAM_SPENDER_HOST", "127.0.0.1").strip() or "127.0.0.1"
DEFAULT_PORT = 8765
MIN_SERVER_PORT = 1024
MAX_SERVER_PORT = 65535

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"
COOKIE_FILE = DATA_DIR / "MAM.cookies"


def clean_port(value: Any, fallback: int = DEFAULT_PORT) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        port = fallback
    return max(MIN_SERVER_PORT, min(MAX_SERVER_PORT, port))


def configured_port() -> int:
    env_port = os.environ.get("MAM_SPENDER_PORT")
    if env_port:
        return clean_port(env_port)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return clean_port(data.get("settings", {}).get("server_port"), DEFAULT_PORT)
        except Exception:
            return DEFAULT_PORT
    return DEFAULT_PORT


PORT = configured_port()


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_file_dialogs_enabled() -> bool:
    if os.environ.get("MAM_SPENDER_FILE_DIALOGS") is not None:
        return env_bool("MAM_SPENDER_FILE_DIALOGS", True)
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        return False
    return True


FILE_DIALOGS_ENABLED = default_file_dialogs_enabled()


def browser_url() -> str:
    browser_host = os.environ.get("MAM_SPENDER_BROWSER_HOST", "").strip()
    if not browser_host:
        browser_host = "127.0.0.1" if HOST in {"0.0.0.0", "::"} else HOST
    return f"http://{browser_host}:{PORT}"

MAM_BASE = "https://www.myanonamouse.net"
MAM_API_ENDPOINT = f"{MAM_BASE}/jsonLoad.php"
POINTS_URL = f"{MAM_BASE}/json/bonusBuy.php/?spendtype=upload&amount="
VIP_URL = f"{MAM_BASE}/json/bonusBuy.php/?spendtype=VIP&duration=max&_={{timestamp}}"
FL_WEDGE_URL = f"{MAM_BASE}/json/bonusBuy.php/?spendtype=wedges&source=points&_={{timestamp}}"

POINTS_PER_BLOCK = 50000
GB_PER_BLOCK = 100
MIN_POINTS_FOR_PURCHASE = 51000
FL_WEDGE_COST = 50000
VIP_RENEW_DAYS = 83
MIN_INTERVAL_MINUTES = 2
MAX_POINTS_BUFFER = 49000


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class Settings:
    buy_vip: bool = True
    buy_fl_before_gb: bool = False
    fl_only: bool = False
    points_buffer: int = 10000
    next_run_delay_minutes: int = 15
    server_port: int = DEFAULT_PORT
    cookie_file_path: str = ""
    plain_session_id: str = ""


@dataclass
class Totals:
    cumulative_upload_gb: int = 0
    cumulative_points_spent: int = 0
    cumulative_freeleech_wedges: int = 0
    cumulative_freeleech_points_spent: int = 0
    cumulative_vip_purchases: int = 0


@dataclass
class UserSummary:
    username: str = "N/A"
    vip_expires: str = "N/A"
    downloaded: str = "N/A"
    uploaded: str = "N/A"
    ratio: str = "N/A"


@dataclass
class RuntimeState:
    settings: Settings = field(default_factory=Settings)
    totals: Totals = field(default_factory=Totals)
    user: UserSummary = field(default_factory=UserSummary)
    running: bool = False
    scheduler_enabled: bool = False
    paused: bool = False
    automation_running: bool = False
    next_run_time: datetime | None = None
    last_scan_points: int | None = None
    last_scan_time: datetime | None = None
    points_per_min: float | None = None
    logs: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    spend_events: list[dict[str, Any]] = field(default_factory=list)


class App:
    def __init__(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.version_lock = threading.RLock()
        self.version_check_running = False
        self.version_status = {
            "current_version": APP_VERSION,
            "current_label": APP_VERSION_LABEL,
            "latest_version": None,
            "latest_url": GITHUB_RELEASES_PAGE,
            "status": "checking",
            "message": "Checking latest release...",
            "checked_at": None,
        }
        self.state = RuntimeState()
        self.load()
        self.log("MAM Spender Web started.")
        self.scheduler = threading.Thread(target=self.scheduler_loop, daemon=True)
        self.scheduler.start()
        self.ensure_version_check()

    def load(self) -> None:
        if not CONFIG_FILE.exists():
            self.save()
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            self.state.settings = self.load_dataclass(Settings, data.get("settings", {}))
            self.normalize_settings()
            self.state.totals = self.load_dataclass(Totals, data.get("totals", {}))
            self.state.last_scan_points = data.get("last_scan_points")
            self.state.last_scan_time = parse_dt(data.get("last_scan_time"))
            self.state.next_run_time = parse_dt(data.get("next_run_time"))
            self.state.scheduler_enabled = bool(data.get("scheduler_enabled", False))
            self.state.history = list(data.get("history", []))[-300:]
            self.state.spend_events = list(data.get("spend_events", []))[-1000:]
        except Exception as exc:
            self.log(f"Could not load config: {exc}")

    @staticmethod
    def load_dataclass(cls: type, values: dict[str, Any]) -> Any:
        allowed = {item.name for item in fields(cls)}
        merged = {**asdict(cls()), **{key: value for key, value in values.items() if key in allowed}}
        return cls(**merged)

    def normalize_settings(self) -> None:
        settings = self.state.settings
        settings.points_buffer = max(0, min(MAX_POINTS_BUFFER, int(settings.points_buffer)))
        settings.next_run_delay_minutes = max(MIN_INTERVAL_MINUTES, int(settings.next_run_delay_minutes))
        settings.server_port = clean_port(settings.server_port)
        settings.cookie_file_path = str(settings.cookie_file_path or "").strip()
        settings.plain_session_id = self.extract_mam_id(str(settings.plain_session_id or ""))

    def save(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        payload = {
            "settings": asdict(self.state.settings),
            "totals": asdict(self.state.totals),
            "last_scan_points": self.state.last_scan_points,
            "last_scan_time": iso_or_none(self.state.last_scan_time),
            "next_run_time": iso_or_none(self.state.next_run_time),
            "scheduler_enabled": self.state.scheduler_enabled,
            "history": self.state.history[-300:],
            "spend_events": self.state.spend_events[-1000:],
        }
        CONFIG_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def log(self, message: str) -> None:
        with self.lock:
            stamp = now_local().strftime("%H:%M:%S")
            self.state.logs.append(f"[{stamp}] {message}")
            self.state.logs = self.state.logs[-500:]

    def ensure_version_check(self) -> None:
        with self.version_lock:
            checked_at = parse_dt(self.version_status.get("checked_at"))
            fresh = checked_at and (now_local() - checked_at).total_seconds() < VERSION_CHECK_SECONDS
            if fresh or self.version_check_running:
                return
            self.version_check_running = True
        threading.Thread(target=self.check_latest_release, daemon=True).start()

    def check_latest_release(self) -> None:
        try:
            request = urllib.request.Request(
                GITHUB_RELEASES_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "MAM-Spender-Web",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=8) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    self.set_version_status(
                        "no_release",
                        "No GitHub release found yet.",
                        latest_version=None,
                        latest_url=GITHUB_RELEASES_PAGE,
                    )
                    return
                raise

            latest_version = str(payload.get("tag_name") or payload.get("name") or "").strip()
            latest_url = str(payload.get("html_url") or GITHUB_RELEASES_PAGE)
            if not latest_version:
                self.set_version_status(
                    "unknown",
                    "Could not read latest release version.",
                    latest_version=None,
                    latest_url=latest_url,
                )
                return

            if self.compare_versions(latest_version, APP_VERSION) > 0:
                self.set_version_status(
                    "update_available",
                    f"Update available: {latest_version}.",
                    latest_version=latest_version,
                    latest_url=latest_url,
                )
            else:
                self.set_version_status(
                    "current",
                    f"Current version: {APP_VERSION_LABEL}.",
                    latest_version=latest_version,
                    latest_url=latest_url,
                )
        except Exception as exc:
            self.set_version_status(
                "error",
                f"Version check failed: {exc}",
                latest_version=None,
                latest_url=GITHUB_RELEASES_PAGE,
            )
        finally:
            with self.version_lock:
                self.version_check_running = False

    def set_version_status(
        self,
        status: str,
        message: str,
        latest_version: str | None,
        latest_url: str,
    ) -> None:
        with self.version_lock:
            self.version_status = {
                "current_version": APP_VERSION,
                "current_label": APP_VERSION_LABEL,
                "latest_version": latest_version,
                "latest_url": latest_url,
                "status": status,
                "message": message,
                "checked_at": now_local().isoformat(),
            }

    def release_status(self) -> dict[str, Any]:
        self.ensure_version_check()
        with self.version_lock:
            return dict(self.version_status)

    @staticmethod
    def version_parts(value: str) -> tuple[int, ...]:
        cleaned = re.sub(r"^[^\d]+", "", str(value).lower())
        cleaned = re.split(r"[-+\s]", cleaned, maxsplit=1)[0]
        parts = []
        for item in cleaned.split("."):
            match = re.match(r"\d+", item)
            parts.append(int(match.group(0)) if match else 0)
        return tuple(parts or [0])

    @classmethod
    def compare_versions(cls, left: str, right: str) -> int:
        left_parts = list(cls.version_parts(left))
        right_parts = list(cls.version_parts(right))
        width = max(len(left_parts), len(right_parts))
        left_parts.extend([0] * (width - len(left_parts)))
        right_parts.extend([0] * (width - len(right_parts)))
        return (left_parts > right_parts) - (left_parts < right_parts)

    def public_state(self) -> dict[str, Any]:
        release_status = self.release_status()
        with self.lock:
            next_run = self.state.next_run_time
            remaining = None
            if next_run:
                remaining = max(0, int((next_run - now_local()).total_seconds()))
            cookie_path = self.state.settings.cookie_file_path
            public_settings = asdict(self.state.settings)
            public_settings.pop("plain_session_id", None)
            return {
                "app_version": APP_VERSION,
                "app_version_label": APP_VERSION_LABEL,
                "release_status": release_status,
                "settings": public_settings,
                "totals": asdict(self.state.totals),
                "user": asdict(self.state.user),
                "running": self.state.running,
                "scheduler_enabled": self.state.scheduler_enabled,
                "paused": self.state.paused,
                "automation_running": self.state.automation_running,
                "next_run_time": iso_or_none(next_run),
                "next_run_seconds": remaining,
                "last_scan_points": self.state.last_scan_points,
                "points_per_min": self.state.points_per_min,
                "active_port": PORT,
                "cookie_exists": Path(cookie_path).expanduser().exists() if cookie_path else False,
                "session_id_saved": bool(self.state.settings.plain_session_id),
                "file_dialogs_enabled": FILE_DIALOGS_ENABLED,
                "default_session_id_file": str(COOKIE_FILE),
                "logs": list(self.state.logs),
                "history": list(reversed(self.state.history[-200:])),
                "spend_events": list(self.state.spend_events[-500:]),
                "constants": {
                    "points_per_block": POINTS_PER_BLOCK,
                    "gb_per_block": GB_PER_BLOCK,
                    "min_points_for_purchase": MIN_POINTS_FOR_PURCHASE,
                    "fl_wedge_cost": FL_WEDGE_COST,
                    "vip_renew_days": VIP_RENEW_DAYS,
                    "min_interval_minutes": MIN_INTERVAL_MINUTES,
                    "max_points_buffer": MAX_POINTS_BUFFER,
                    "default_server_port": DEFAULT_PORT,
                    "min_server_port": MIN_SERVER_PORT,
                    "max_server_port": MAX_SERVER_PORT,
                },
            }

    def update_settings(self, incoming: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            settings = self.state.settings
            for key in ("buy_vip", "buy_fl_before_gb", "fl_only"):
                if key in incoming:
                    setattr(settings, key, bool(incoming[key]))
            if "points_buffer" in incoming:
                settings.points_buffer = max(0, min(MAX_POINTS_BUFFER, int(incoming["points_buffer"])))
            if "next_run_delay_minutes" in incoming:
                minutes = int(incoming["next_run_delay_minutes"])
                settings.next_run_delay_minutes = max(MIN_INTERVAL_MINUTES, minutes)
            if "server_port" in incoming:
                settings.server_port = clean_port(incoming["server_port"])
            if "cookie_file_path" in incoming:
                path = str(incoming["cookie_file_path"]).strip()
                settings.cookie_file_path = path
            self.normalize_settings()
            self.save()
        self.log("Settings saved.")
        return self.public_state()

    def add_history(self, entry: dict[str, Any]) -> None:
        with self.lock:
            self.state.history.append({"created_at": now_local().isoformat(), **entry})
            self.state.history = self.state.history[-300:]
            self.save()

    def add_spend_event(
        self,
        category: str,
        label: str,
        points_spent: int,
        units: int = 0,
        unit_label: str = "",
        balance_after: int | None = None,
    ) -> None:
        if points_spent <= 0:
            return
        event = {
            "created_at": now_local().isoformat(),
            "category": category,
            "label": label,
            "points_spent": points_spent,
            "units": units,
            "unit_label": unit_label,
            "balance_after": balance_after,
        }
        with self.lock:
            self.state.spend_events.append(event)
            self.state.spend_events = self.state.spend_events[-1000:]
            self.save()

    def save_session_id(self, value: str, save_mode: str = "file") -> dict[str, Any]:
        value = self.extract_mam_id(value)
        if not value:
            raise ValueError("Mam Session_ID value is empty.")
        if save_mode == "plain":
            with self.lock:
                self.state.settings.plain_session_id = value
                self.save()
            self.log("Mam Session_ID saved in local app settings as plain text.")
            return self.public_state()

        if FILE_DIALOGS_ENABLED:
            try:
                target = self.choose_cookie_save_path()
            except RuntimeError as exc:
                self.log(f"Save dialog unavailable; saving to default data file instead: {exc}")
                target = COOKIE_FILE
        else:
            with self.lock:
                path_value = self.state.settings.cookie_file_path.strip()
            target = Path(path_value).expanduser() if path_value else COOKIE_FILE
            if not target.is_absolute():
                target = DATA_DIR / target

        if not target:
            self.log("Mam Session_ID save canceled.")
            return self.public_state()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")
        with self.lock:
            self.state.settings.cookie_file_path = str(target)
            self.state.settings.plain_session_id = ""
            self.save()
        self.log(f"Mam Session_ID saved to {target}.")
        return self.public_state()

    def choose_cookie_save_path(self) -> Path | None:
        if not FILE_DIALOGS_ENABLED:
            return COOKIE_FILE
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:
            raise RuntimeError(f"Save dialog is not available: {exc}") from exc

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.asksaveasfilename(
                title="Save Mam Session_ID cookie file",
                defaultextension=".cookies",
                initialfile="MAM.cookies",
                filetypes=[
                    ("Cookie files", "*.cookies"),
                    ("Text files", "*.txt"),
                    ("All files", "*.*"),
                ],
            )
        finally:
            root.destroy()
        return Path(selected).expanduser() if selected else None

    def check_cookie_file(self, path_value: str | None = None) -> dict[str, Any]:
        with self.lock:
            if path_value is not None:
                path_value = str(path_value).strip()
                if path_value:
                    self.state.settings.cookie_file_path = path_value
                    self.save()
            cookie_file = self.state.settings.cookie_file_path
        mam_id = self.read_cookie_file(cookie_file)
        self.log(f"Mam Session_ID file check OK. Found value ending in ...{mam_id[-6:]}.")
        return self.public_state()

    def browse_cookie_file(self) -> dict[str, Any]:
        if not FILE_DIALOGS_ENABLED:
            raise RuntimeError(
                "File picker is disabled in Docker. Put the file in the mounted data folder "
                "and enter /app/data/filename, or paste the Session_ID and click Save Session_ID."
            )
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:
            raise RuntimeError(
                "File picker is not available in this environment. Put the file in the mounted data folder "
                "and enter its path, or paste the Session_ID and click Save Session_ID."
            ) from exc

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askopenfilename(
                title="Select Mam Session_ID cookie file or export",
                filetypes=[
                    ("Cookie files", "*.cookies *.txt *.json"),
                    ("All files", "*.*"),
                ],
            )
        finally:
            root.destroy()

        if not selected:
            self.log("Mam Session_ID file browse canceled.")
            return self.public_state()

        with self.lock:
            self.state.settings.cookie_file_path = selected
            self.save()

        try:
            mam_id = self.read_cookie_file(selected)
            self.log(f"Mam Session_ID file selected. Found value ending in ...{mam_id[-6:]}.")
        except Exception as exc:
            self.log(f"Mam Session_ID file selected, but a value was not found: {exc}")
        return self.public_state()

    def reset_totals(self) -> dict[str, Any]:
        with self.lock:
            self.state.totals = Totals()
            self.save()
        self.log("Cumulative totals reset.")
        self.add_history({"kind": "manual", "result": "Cumulative totals reset."})
        return self.public_state()

    def start_scheduler(self) -> dict[str, Any]:
        with self.lock:
            self.state.running = True
            self.state.scheduler_enabled = True
            self.state.paused = False
            self.state.next_run_time = now_local() + timedelta(minutes=self.state.settings.next_run_delay_minutes)
            self.save()
        self.log("Schedule started.")
        return self.public_state()

    def pause_scheduler(self) -> dict[str, Any]:
        with self.lock:
            self.state.paused = True
            self.state.running = False
            self.state.scheduler_enabled = False
            self.save()
        self.log("Schedule paused.")
        return self.public_state()

    def run_now(self, fl_only_override: bool = False) -> dict[str, Any]:
        with self.lock:
            if self.state.automation_running:
                self.log("Already running.")
                return self.public_state()
            self.state.automation_running = True
        thread = threading.Thread(target=self._run_and_reschedule, args=(fl_only_override,), daemon=True)
        thread.start()
        self.log("Manual run requested.")
        return self.public_state()

    def _run_and_reschedule(self, fl_only_override: bool) -> None:
        try:
            self.run_automation(fl_only_override)
        finally:
            with self.lock:
                self.state.automation_running = False
                if self.state.scheduler_enabled and not self.state.paused:
                    self.state.next_run_time = now_local() + timedelta(
                        minutes=self.state.settings.next_run_delay_minutes
                    )
                    self.log(f"Next run scheduled for {self.state.next_run_time.strftime('%b %d, %Y %I:%M %p')}.")
                self.save()

    def scheduler_loop(self) -> None:
        while True:
            time.sleep(1)
            with self.lock:
                due = (
                    self.state.scheduler_enabled
                    and not self.state.paused
                    and not self.state.automation_running
                    and self.state.next_run_time is not None
                    and now_local() >= self.state.next_run_time
                )
            if due:
                self._run_and_reschedule(False)

    def run_automation(self, fl_only_override: bool = False) -> None:
        self.log("Starting automation process.")
        started_at = now_local()
        result = "Completed"
        points_start: int | None = None
        points_end: int | None = None
        vip_purchased = False
        fl_wedges_purchased = 0
        actual_purchased_gb = 0
        run_points_spent = 0
        with self.lock:
            settings = Settings(**asdict(self.state.settings))
        try:
            cookies = self.load_cookies(settings)
            mam_uid = self.get_session_id(cookies)
            if not mam_uid:
                self.log("Session invalid. Please check your Mam Session_ID.")
                result = "Session invalid. Check Mam Session_ID."
                return
            self.log("Session valid.")

            try:
                summary = self.get_user_summary(cookies)
                with self.lock:
                    self.state.user = summary
            except Exception as exc:
                self.log(f"Failed to update user information: {exc}")

            self.log("Collecting current points.")
            points = self.get_seed_bonus(cookies, mam_uid)
            initial_points = points
            points_start = points
            points_end = points
            if points <= 0:
                self.log("Failed to retrieve bonus points.")
                result = "Failed to retrieve bonus points."
                return
            self.log(f"Current points: {points:,}")
            self.update_points_per_min(points)

            if settings.buy_vip:
                vip_expiry = self.get_vip_expiry(cookies)
                vip_remaining = vip_expiry - now_local()
                self.log(
                    f"Current VIP expiry: {vip_expiry.strftime('%b %d, %Y %I:%M %p')} "
                    f"({vip_remaining.total_seconds() / 86400:.1f} days remaining)"
                )
                if vip_remaining.total_seconds() / 86400 <= VIP_RENEW_DAYS:
                    vip_result = self.mam_json(VIP_URL.format(timestamp=self.timestamp_ms()), cookies)
                    if bool(vip_result.get("success")):
                        self.log("VIP purchase successful.")
                        vip_purchased = True
                        new_points = self.get_seed_bonus(cookies, mam_uid)
                        vip_points_spent = max(points - new_points, 0)
                        points = new_points
                        points_end = points
                        if vip_points_spent > 0:
                            self.add_spend_event("vip", "VIP Renewal", vip_points_spent, 1, "renewal", points)
                    else:
                        self.log("VIP purchase failed or not available.")
                else:
                    self.log(f"VIP purchase not required; current VIP period exceeds {VIP_RENEW_DAYS} days.")

            should_buy_wedge = settings.buy_fl_before_gb or settings.fl_only or fl_only_override
            if should_buy_wedge:
                if points < FL_WEDGE_COST + settings.points_buffer:
                    self.log("Not enough points to buy Freeleech Wedge (requires 50,000 + buffer).")
                else:
                    self.log("Attempting Freeleech Wedge purchase.")
                    if self.buy_freeleech_wedge(cookies, mam_uid):
                        fl_wedges_purchased = 1
                        new_points = self.get_seed_bonus(cookies, mam_uid)
                        wedge_points_spent = max(points - new_points, 0)
                        points = new_points
                        points_end = points
                        self.add_spend_event(
                            "freeleech_wedge",
                            "Freeleech Wedge",
                            wedge_points_spent or FL_WEDGE_COST,
                            1,
                            "wedge",
                            points,
                        )
                        self.log("Freeleech Wedge purchase confirmed.")
                    else:
                        self.log("Freeleech Wedge purchase failed (points did not decrease).")

            if settings.fl_only or fl_only_override:
                run_points_spent = max(initial_points - points, 0)
                points_end = points
                self.update_totals(0, run_points_spent, fl_wedges_purchased, vip_purchased)
                self.log("FL-only mode enabled; skipping upload GB purchases.")
                self.log_summary(vip_purchased, fl_wedges_purchased, 0, run_points_spent)
                return

            upload_purchase_threshold = max(MIN_POINTS_FOR_PURCHASE, POINTS_PER_BLOCK + settings.points_buffer)
            if points < upload_purchase_threshold:
                self.log(
                    f"Not enough points ({points:,}). Need at least {upload_purchase_threshold:,} "
                    f"to purchase {GB_PER_BLOCK} GiB while keeping a {settings.points_buffer:,}-point buffer."
                )
            else:
                self.log(
                    f"{points:,} points available. Purchasing {GB_PER_BLOCK} GiB "
                    f"of upload for {POINTS_PER_BLOCK:,} points while keeping "
                    f"a {settings.points_buffer:,}-point buffer."
                )
                self.mam_json(POINTS_URL + str(GB_PER_BLOCK), cookies)
                points -= POINTS_PER_BLOCK
                points_end = points
                actual_purchased_gb = GB_PER_BLOCK
                self.add_spend_event(
                    "upload_credit",
                    "Upload Credit",
                    POINTS_PER_BLOCK,
                    GB_PER_BLOCK,
                    "GiB",
                    points,
                )
                self.log(f"After purchase, points: {points:,}")

            run_points_spent = max(initial_points - points, 0)
            points_end = points
            self.update_totals(actual_purchased_gb, run_points_spent, fl_wedges_purchased, vip_purchased)
            self.log_summary(vip_purchased, fl_wedges_purchased, actual_purchased_gb, run_points_spent)
        except Exception as exc:
            self.log(f"An unexpected error occurred: {exc}")
            result = f"Error: {exc}"
        finally:
            self.add_history(
                {
                    "kind": "run",
                    "started_at": started_at.isoformat(),
                    "result": result,
                    "points_before": points_start,
                    "points_after": points_end,
                    "points_spent": run_points_spent,
                    "upload_gb": actual_purchased_gb,
                    "freeleech_wedges": fl_wedges_purchased,
                    "vip_purchased": vip_purchased,
                }
            )

    def load_cookies(self, settings: Settings) -> dict[str, str]:
        if settings.plain_session_id:
            return {"mam_id": settings.plain_session_id}
        return {"mam_id": self.read_cookie_file(settings.cookie_file_path)}

    def read_cookie_file(self, cookie_file: str) -> str:
        if not str(cookie_file).strip():
            raise RuntimeError("Enter a Mam Session_ID file path first, or paste and save a Session_ID.")
        path = Path(cookie_file).expanduser()
        if not path.exists():
            if path == COOKIE_FILE:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
                raise RuntimeError("Cookie file created. Please paste your Mam Session_ID into it.")
            raise RuntimeError(f"Cookie file not found: {path}")
        raw = path.read_text(encoding="utf-8", errors="ignore")
        mam_id = self.extract_mam_id(raw)
        if not mam_id:
            raise RuntimeError("Could not find a Mam Session_ID value in that file.")
        return mam_id

    def opener(self, cookies: dict[str, str]) -> urllib.request.OpenerDirector:
        cookie_header = f"mam_id={urllib.parse.quote(cookies['mam_id'])}"
        opener = urllib.request.build_opener()
        opener.addheaders = [
            ("User-Agent", "MAM-Spender-Web"),
            ("Cookie", cookie_header),
            ("Accept", "application/json,text/plain,*/*"),
        ]
        return opener

    def mam_json(self, url: str, cookies: dict[str, str]) -> dict[str, Any]:
        try:
            with self.opener(cookies).open(url, timeout=30) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MAM returned non-JSON response: {body[:200]}") from exc

    def get_session_id(self, cookies: dict[str, str]) -> str:
        data = self.mam_json(MAM_API_ENDPOINT + "?snatch_summary", cookies)
        return str(data.get("uid", ""))

    def get_user_summary(self, cookies: dict[str, str]) -> UserSummary:
        data = self.mam_json(MAM_API_ENDPOINT + "?snatch_summary", cookies)
        return UserSummary(
            username=str(data.get("username") or "N/A"),
            vip_expires=self.format_vip(data.get("vip_until")),
            downloaded=str(data.get("downloaded") or "N/A"),
            uploaded=str(data.get("uploaded") or "N/A"),
            ratio=str(data.get("ratio") or "N/A"),
        )

    def get_seed_bonus(self, cookies: dict[str, str], mam_uid: str) -> int:
        data = self.mam_json(f"{MAM_API_ENDPOINT}?uid={urllib.parse.quote(mam_uid)}", cookies)
        try:
            return int(data.get("seedbonus") or 0)
        except (TypeError, ValueError):
            return 0

    def get_vip_expiry(self, cookies: dict[str, str]) -> datetime:
        data = self.mam_json(MAM_API_ENDPOINT, cookies)
        value = str(data.get("vip_until") or "")
        parsed = self.parse_mam_date(value)
        if parsed:
            return parsed
        return datetime(1970, 1, 1, tzinfo=now_local().tzinfo)

    def buy_freeleech_wedge(self, cookies: dict[str, str], mam_uid: str) -> bool:
        before = self.get_seed_bonus(cookies, mam_uid)
        url = FL_WEDGE_URL.format(timestamp=self.timestamp_ms())
        self.log(f"Wedge request URL: {url}")
        self.mam_json(url, cookies)
        time.sleep(0.8)
        after = self.get_seed_bonus(cookies, mam_uid)
        self.log(f"Wedge verification: before={before:,}, after={after:,}")
        return before - after >= FL_WEDGE_COST

    def update_points_per_min(self, current_points: int) -> None:
        with self.lock:
            previous_points = self.state.last_scan_points
            previous_time = self.state.last_scan_time
            if previous_points and previous_time:
                points_earned = current_points - previous_points
                minutes_elapsed = (now_local() - previous_time).total_seconds() / 60
                if points_earned > 0 and minutes_elapsed >= 1:
                    self.state.points_per_min = points_earned / minutes_elapsed
                    self.log(
                        f"Points/min: {self.state.points_per_min:.1f} "
                        f"({points_earned:,} pts over {minutes_elapsed:.0f} min)."
                    )
                else:
                    self.state.points_per_min = 0.0 if points_earned <= 0 else None
            else:
                self.state.points_per_min = None
            self.state.last_scan_points = current_points
            self.state.last_scan_time = now_local()
            self.save()

    def update_totals(self, gb_bought: int, points_spent: int, fl_wedges: int = 0, vip_purchased: bool = False) -> None:
        with self.lock:
            if gb_bought <= 0 and points_spent <= 0 and fl_wedges <= 0 and not vip_purchased:
                self.log("No points spent this run; totals unchanged.")
                return
            self.state.totals.cumulative_upload_gb += max(gb_bought, 0)
            self.state.totals.cumulative_points_spent += max(points_spent, 0)
            self.state.totals.cumulative_freeleech_wedges += max(fl_wedges, 0)
            self.state.totals.cumulative_freeleech_points_spent += max(fl_wedges, 0) * FL_WEDGE_COST
            if vip_purchased:
                self.state.totals.cumulative_vip_purchases += 1
            self.save()
        if gb_bought > 0 and points_spent > 0:
            self.log(f"Confirmed purchase: {gb_bought} GiB for {points_spent:,} points.")
        elif points_spent > 0:
            self.log(f"Confirmed purchase: 0 GiB upload credit for {points_spent:,} points.")

    def log_summary(self, vip: bool, wedges: int, gb: int, points_spent: int) -> None:
        self.log("=== Summary ===")
        self.log(f"VIP Purchase: {'Yes' if vip else 'No'}")
        self.log(f"Freeleech Wedges Purchased: {wedges}")
        self.log(f"Upload GB Purchased: {gb} GiB" if gb else "No upload credit purchased this run.")
        self.log(f"Points Spent This Run: {points_spent:,}")

    @staticmethod
    def timestamp_ms() -> str:
        return str(int(datetime.now(tz=timezone.utc).timestamp() * 1000))

    @staticmethod
    def extract_mam_id(value: str) -> str:
        value = value.strip()
        if not value:
            return ""

        json_value = App.extract_mam_id_from_json(value)
        if json_value:
            return json_value

        patterns = [
            r"(?:^|[;\s,])mam_id\s*=\s*['\"]?([^;,\s'\"]+)",
            r"['\"]name['\"]\s*:\s*['\"]mam_id['\"][\s\S]{0,240}?['\"]value['\"]\s*:\s*['\"]([^'\"]+)",
            r"myanonamouse\.net\s+\S+\s+\S+\s+\S+\s+\S+\s+mam_id\s+([^\s]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                return App.clean_cookie_value(match.group(1))

        for line in value.splitlines():
            parts = line.strip().split()
            if len(parts) >= 7 and parts[-2].lower() == "mam_id":
                return App.clean_cookie_value(parts[-1])

        if "\n" not in value and "=" not in value and ";" not in value and len(value) >= 12:
            return App.clean_cookie_value(value)
        return ""

    @staticmethod
    def extract_mam_id_from_json(value: str) -> str:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return ""

        def walk(item: Any) -> str:
            if isinstance(item, dict):
                lowered = {str(key).lower(): val for key, val in item.items()}
                if "mam_id" in lowered:
                    return App.clean_cookie_value(str(lowered["mam_id"]))
                if str(lowered.get("name", "")).lower() == "mam_id" and "value" in lowered:
                    return App.clean_cookie_value(str(lowered["value"]))
                for val in item.values():
                    found = walk(val)
                    if found:
                        return found
            elif isinstance(item, list):
                for val in item:
                    found = walk(val)
                    if found:
                        return found
            return ""

        return walk(parsed)

    @staticmethod
    def clean_cookie_value(value: str) -> str:
        value = urllib.parse.unquote(value.strip().strip("'\""))
        if value.lower().startswith("mam_id="):
            value = value.split("=", 1)[1]
        if ";" in value:
            value = value.split(";", 1)[0]
        return value.strip()

    @staticmethod
    def parse_mam_date(value: str) -> datetime | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%b %d, %Y %I:%M %p"):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.replace(tzinfo=now_local().tzinfo)
            except ValueError:
                pass
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=now_local().tzinfo)
        except ValueError:
            return None

    def format_vip(self, value: Any) -> str:
        parsed = self.parse_mam_date(str(value or ""))
        return parsed.strftime("%b %d, %Y %I:%M %p") if parsed else str(value or "N/A")


APP = App()


class Handler(BaseHTTPRequestHandler):
    server_version = "MAMSpenderWeb/1.0"

    def do_GET(self) -> None:
        if self.path == "/api/state":
            self.write_json(APP.public_state())
            return
        if self.path == "/":
            self.serve_file(STATIC_DIR / "index.html")
            return
        if self.path.startswith("/static/"):
            requested = self.path.removeprefix("/static/")
            self.serve_file(STATIC_DIR / requested)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            data = self.read_json()
            if self.path == "/api/settings":
                self.write_json(APP.update_settings(data))
            elif self.path == "/api/session_id":
                self.write_json(
                    APP.save_session_id(
                        str(data.get("session_id", "")),
                        str(data.get("save_mode", "file")),
                    )
                )
            elif self.path == "/api/cookie":
                self.write_json(APP.save_session_id(str(data.get("mam_id", "")), "file"))
            elif self.path == "/api/check_cookie_file":
                self.write_json(APP.check_cookie_file(data.get("cookie_file_path")))
            elif self.path == "/api/browse_cookie_file":
                self.write_json(APP.browse_cookie_file())
            elif self.path == "/api/run":
                self.write_json(APP.run_now(bool(data.get("fl_only_override", False))))
            elif self.path == "/api/start":
                self.write_json(APP.start_scheduler())
            elif self.path == "/api/pause":
                self.write_json(APP.pause_scheduler())
            elif self.path == "/api/reset_totals":
                self.write_json(APP.reset_totals())
            else:
                self.write_json(
                    {"error": "That app action is not available. Restart MAM Spender Web and try again."},
                    status=HTTPStatus.NOT_FOUND,
                )
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def serve_file(self, path: Path) -> None:
        path = path.resolve()
        if STATIC_DIR.resolve() not in path.parents and path != (STATIC_DIR / "index.html").resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    bind_url = f"http://{HOST}:{PORT}"
    url = browser_url()
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"Could not start MAM Spender Web on {bind_url}: {exc}")
        print("Try a different server port in Settings, or close the app already using this port.")
        try:
            input("Press Enter to close...")
        except EOFError:
            pass
        return
    print(f"MAM Spender Web is listening on {bind_url}")
    print(f"Open {url} in your browser.")
    print("Close this window to stop it.")
    if env_bool("MAM_SPENDER_OPEN_BROWSER", True):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
