from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

import psutil
import requests
from PIL import Image
from pypresence import Presence

from . import telemetry
from .kill_tracker import KillTracker, PlayerIdentity
from .user_config import get_or_prompt_username, read_username
from .vehicle_images import VehicleImageResolver


DEFAULT_LARGE_IMAGE = (
    os.getenv("WARTHUNDER_RPC_LARGE_IMAGE", "https://unixcore.sh/wt1.webp")
    or os.getenv("WARTHUNDER_RPC_LARGE_IMAGE_KEY", "wt-logo")
).strip()

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeOptions:
    mode: str = "local"
    prompt_for_username: bool = True
    check_process_running: Optional[Callable[[], bool]] = None
    logger: Optional[logging.Logger] = None
    stop_requested: Optional[Callable[[], bool]] = None
    active_interval: int = 3
    idle_interval: int = 10
    telemetry_grace_seconds: int = 20
    rpc_retry_interval: int = 5
    clear_presence_on_game_exit: bool = True
    discord_retry_backoff_max: int = 60
    time_provider: Callable[[], float] = time.time
    sleep_provider: Callable[[float], None] = time.sleep


class WarThunderRPCApp:
    def __init__(
        self,
        options: Optional[RuntimeOptions] = None,
        *,
        player_name: Optional[str] = None,
        rpc_factory: Callable[[str], Presence] = Presence,
    ):
        self.options = options or RuntimeOptions()
        self.logger = self.options.logger or LOGGER
        self.rpc_factory = rpc_factory
        self.client_id = "1211769535468937237"
        self.rpc = None
        self.clock_timer = int(self.now())
        self.base_url = "http://127.0.0.1:8111"
        self.check_process_running = self.options.check_process_running or self._is_aces_running
        self.stop_requested = self.options.stop_requested or (lambda: False)
        self.image_resolver = VehicleImageResolver(logger=self.logger)

        self.runtime_state = "game_not_running"
        self.last_good_state = None
        self.last_presence_payload = None
        self.last_telemetry_ok_at = None
        self.last_rpc_error_at = None
        self.presence_active = False
        self.rpc_connected = False
        self._rpc_retry_delay = max(1, self.options.rpc_retry_interval)
        self._next_rpc_connect_at = 0.0
        self._logged_messages = set()

        if player_name is None:
            if self.options.prompt_for_username:
                player_name = get_or_prompt_username(prompt_if_missing=True)
            else:
                player_name = read_username()

        self.player_name = player_name
        self.kill_tracker = KillTracker(PlayerIdentity(self.player_name))

    def now(self):
        return float(self.options.time_provider())

    @staticmethod
    def _is_aces_running():
        for process in psutil.process_iter(["name"]):
            try:
                if (process.info.get("name") or "").lower() == "aces.exe":
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False

    def _log_once(self, key, level, message, *args):
        if key in self._logged_messages:
            return
        self._logged_messages.add(key)
        self.logger.log(level, message, *args)

    def _clear_log_once(self, *keys):
        for key in keys:
            self._logged_messages.discard(key)

    def _set_runtime_state(self, state):
        self.runtime_state = state

    def _mark_rpc_unavailable(self, exc):
        self.last_rpc_error_at = self.now()
        self.rpc_connected = False
        self._set_runtime_state("discord_unavailable")
        self._log_once("discord_unavailable", logging.WARNING, "Discord RPC unavailable: %s", exc)
        self._next_rpc_connect_at = self.now() + self._rpc_retry_delay
        self._rpc_retry_delay = min(
            max(1, self.options.discord_retry_backoff_max),
            max(1, self._rpc_retry_delay * 2),
        )
        self.disconnect_rpc()

    def _reset_rpc_backoff(self):
        self._rpc_retry_delay = max(1, self.options.rpc_retry_interval)
        self._next_rpc_connect_at = 0.0
        self._clear_log_once("discord_unavailable")

    def connect_rpc(self):
        if self.rpc is not None:
            return True

        if self.now() < self._next_rpc_connect_at:
            return False

        try:
            self.rpc = self.rpc_factory(self.client_id)
            self.rpc.connect()
        except Exception as exc:
            self._mark_rpc_unavailable(exc)
            return False

        self.rpc_connected = True
        self.clock_timer = int(self.now())
        self._reset_rpc_backoff()
        self._log_once("rpc_recovered", logging.INFO, "Discord RPC connected")
        return True

    def disconnect_rpc(self):
        if self.rpc is None:
            self.rpc_connected = False
            return

        try:
            self.rpc.close()
        except Exception as exc:
            self.logger.debug("Error closing Discord RPC: %s", exc)
        finally:
            self.rpc = None
            self.rpc_connected = False

    def fetch_hudmsg(self, last_evt=0, last_dmg=0):
        try:
            response = requests.get(
                f"{self.base_url}/hudmsg?lastEvt={last_evt}&lastDmg={last_dmg}",
                timeout=2,
            )
            response.raise_for_status()
            data = response.json()
            return data["damage"], data["events"]
        except Exception as exc:
            self.logger.debug("Error fetching hudmsg: %s", exc)
            return [], []

    def get_map_obj_info(self):
        try:
            response = requests.get(f"{self.base_url}/map_obj.json", timeout=2)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            self.logger.debug("Error fetching map objects: %s", exc)
            return "Unknown"

        friendly_zones = 0
        enemy_zones = 0
        for obj in data:
            if obj.get("type") != "capture_zone":
                continue

            color = obj.get("color")
            if color == "#174DFF":
                friendly_zones += 1
            elif color == "#fa0C00":
                enemy_zones += 1

        if friendly_zones > enemy_zones:
            return "Winning"
        if friendly_zones < enemy_zones:
            return "Losing"
        return "Tied"

    @staticmethod
    def get_match_type(objective, vehicle_type):
        objective_mapping = {
            "Capture the enemy point": "Battle",
            "Capture and maintain superiority over the points": "Domination",
            "Capture and maintain superiority over the airfields": "Air Domination",
            "Capture and hold airfields": "Air Domination",
            "Prevent capture of allied point": "Battle",
            "Capture and keep hold of the point": "Conquest",
            "Capture and hold the airfield": "Air Domination",
            "Capture and maintain superiority over the air zone": "Air Domination",
            "Destroy the enemy ground vehicles": "Ground Strike",
            "Destroy the highlighted targets": "Frontline",
            "Prevent the capture of the allied point": "Battle",
        }

        base_type = "Ground" if vehicle_type == "tank" else "Air"
        match_type = objective_mapping.get(objective, "Operations")
        if base_type == "Air" and match_type in ["Battle", "Domination", "Conquest"]:
            return f"Ground {match_type}"
        if base_type == "Air":
            return f"Air {match_type}"
        return f"Ground {match_type}"

    def get_json_data(self, endpoint):
        try:
            response = requests.get(f"{self.base_url}/{endpoint}", timeout=2)
            response.raise_for_status()
            return json.loads(response.text)
        except Exception as exc:
            self.logger.debug("Error fetching %s: %s", endpoint, exc)
            return None

    def get_latest_damage_id(self):
        damage_msgs, _ = self.fetch_hudmsg(0, 0)
        return self.kill_tracker.latest_damage_id(damage_msgs)

    def update_kill_count(self, in_match_session):
        if not in_match_session:
            self.kill_tracker.reset_session()
            return

        if not self.kill_tracker.session_active:
            self.kill_tracker.start_session(seed_damage_id=self.get_latest_damage_id())
            return

        damage_msgs, _ = self.fetch_hudmsg(0, self.kill_tracker.last_damage_id)
        self.kill_tracker.ingest_damage_messages(damage_msgs)

    @staticmethod
    def build_health_status(indicators):
        crew_current = WarThunderRPCApp._format_crew_value(indicators.get("crew_current", 0))
        crew_total = WarThunderRPCApp._format_crew_value(indicators.get("crew_total", 1))
        return f"{crew_current}/{crew_total} Crew"

    @staticmethod
    def _format_crew_value(value):
        text = str(value)
        return text[:-2] if text.endswith(".0") else text

    def fetch_map_image(self):
        try:
            response = requests.get(f"{self.base_url}/map.img", timeout=2)
            response.raise_for_status()
            with Image.open(io.BytesIO(response.content)) as map_image:
                return map_image.copy()
        except Exception as exc:
            self.logger.debug("Error fetching map image: %s", exc)
            return None

    def get_game_state(self):
        indicators = self.get_json_data("indicators")
        if not indicators:
            return None

        mission = self.get_json_data("mission.json") or {}
        map_info = self.get_json_data("map_info.json") or {}
        raw_vehicle_type = indicators.get("type", "Unknown")
        vehicle_slug = self.image_resolver.extract_vehicle_slug(raw_vehicle_type)
        vehicle_name = self.image_resolver.get_display_name(vehicle_slug)

        state = {
            "is_in_vehicle": indicators.get("valid", False),
            "vehicle_type": indicators.get("army", "Unknown"),
            "vehicle_slug": vehicle_slug,
            "vehicle_name": vehicle_name,
            "vehicle_image_url": None,
            "vehicle_image_status": "fallback_unresolved",
            "in_match": False,
            "main_objective": "false",
            "in_map": map_info.get("valid", False),
            "current_map": "Unknown",
            "kill_count": self.kill_tracker.kill_count,
            "team_status": "Unknown",
            "health_status": self.build_health_status(indicators),
        }

        if mission.get("objectives"):
            raw_objective = mission["objectives"][0].get("text", "false")
            cleaned_objective = re.sub(r"[^\w\s]", "", raw_objective).strip()
            state["main_objective"] = cleaned_objective
            state["in_match"] = mission["objectives"][0].get("primary", False)

        self.update_kill_count(state["in_map"] and state["in_match"])
        state["kill_count"] = self.kill_tracker.kill_count

        if state["in_map"] and state["in_match"]:
            state["team_status"] = self.get_map_obj_info()

        if state["in_map"]:
            map_image = self.fetch_map_image()
            if map_image is not None:
                map_data = telemetry.mapinfo.get_grid_info(map_img=map_image)
                state["current_map"] = map_data["name"].replace("_", " ")

            if state["vehicle_slug"] != "DUMMY_PLANE":
                image_url, image_status = self.image_resolver.resolve(state["vehicle_slug"])
                state["vehicle_image_url"] = image_url
                state["vehicle_image_status"] = image_status

        return state

    def build_presence_data(self, state):
        base_presence = {
            "start": self.clock_timer,
            "large_text": "War Thunder",
        }
        if DEFAULT_LARGE_IMAGE:
            base_presence["large_image"] = DEFAULT_LARGE_IMAGE
        fallback_large_image = base_presence.get("large_image")

        if not state["in_map"]:
            return {**base_presence, "state": "In the hangar", "details": "Browsing vehicles.."}

        if state["vehicle_type"] == "tank":
            country_code = self.image_resolver.get_country_code(state["vehicle_slug"])
            base_presence.update(
                {
                    "small_image": f"https://flagsapi.com/{country_code}/flat/64.png",
                    "small_text": country_code,
                }
            )

        if state["is_in_vehicle"] and state["in_map"] and not state["in_match"]:
            action = "Piloting" if state["vehicle_type"] == "air" else "Driving"
            if state["vehicle_name"] == "DUMMY PLANE":
                return {
                    **base_presence,
                    "state": "Loading into a match..",
                    "details": f"{state['vehicle_type'].capitalize()} Match",
                }

            return {
                **base_presence,
                "state": f"{action} a {state['vehicle_name'].upper()}",
                "details": f"In Test Drive | {state['health_status']}",
                **(
                    {"large_image": state["vehicle_image_url"] or fallback_large_image}
                    if state["vehicle_image_url"] or fallback_large_image
                    else {}
                ),
            }

        if state["is_in_vehicle"] and state["in_map"] and state["in_match"]:
            action = "Piloting" if state["vehicle_type"] == "air" else "Driving"
            match_type = self.get_match_type(state["main_objective"], state["vehicle_type"])
            status_text = f"{match_type}, {state['kill_count']} Kills"
            return {
                **base_presence,
                "state": f"{action} a {state['vehicle_name'].upper()}, {state['health_status']}",
                "details": status_text,
                **(
                    {"large_image": state["vehicle_image_url"] or fallback_large_image}
                    if state["vehicle_image_url"] or fallback_large_image
                    else {}
                ),
                "large_text": state["current_map"],
            }

        return {**base_presence, "state": "Unknown vehicle", "details": "In-game"}

    def _publish_presence(self, presence_data):
        self.last_presence_payload = presence_data
        if not self.connect_rpc():
            return False

        try:
            self.rpc.update(**presence_data)
        except Exception as exc:
            self._mark_rpc_unavailable(exc)
            return False

        self.presence_active = True
        self.rpc_connected = True
        self._clear_log_once("rpc_recovered")
        self.logger.info("Updated presence: %s", presence_data)
        return True

    def clear_presence(self, reason=""):
        if self.rpc is None or not self.presence_active:
            self.presence_active = False
            return True

        try:
            self.rpc.clear()
            self._log_once(
                f"presence_cleared:{reason or 'default'}",
                logging.INFO,
                "Cleared Discord presence%s",
                f" ({reason})" if reason else "",
            )
        except Exception as exc:
            self._mark_rpc_unavailable(exc)
            return False

        self.presence_active = False
        return True

    def _reset_session_state(self):
        self.kill_tracker.reset_session()
        self.last_good_state = None
        self.last_presence_payload = None
        self.last_telemetry_ok_at = None

    def _handle_game_not_running(self):
        self._set_runtime_state("game_not_running")
        self._log_once("game_missing", logging.INFO, "War Thunder not detected; waiting")
        self._clear_log_once("telemetry_gap", "loading_transition")
        if self.options.clear_presence_on_game_exit:
            self.clear_presence("game closed")
        self.disconnect_rpc()
        self._reset_session_state()

    def _handle_telemetry_gap(self):
        telemetry_age = None
        if self.last_telemetry_ok_at is not None:
            telemetry_age = self.now() - self.last_telemetry_ok_at

        in_grace_period = (
            self.last_good_state is not None
            and telemetry_age is not None
            and telemetry_age <= self.options.telemetry_grace_seconds
        )

        if in_grace_period:
            self._set_runtime_state("loading_transition")
            self._log_once(
                "loading_transition",
                logging.INFO,
                "Telemetry temporarily unavailable; preserving last known state",
            )
            self._clear_log_once("telemetry_gap")
            if self.last_presence_payload is not None:
                self._publish_presence(self.last_presence_payload)
            return

        self._set_runtime_state("telemetry_unavailable")
        self._log_once(
            "telemetry_gap",
            logging.INFO,
            "Telemetry unavailable while War Thunder is running; waiting for recovery",
        )
        self._clear_log_once("loading_transition")
        if self.options.clear_presence_on_game_exit:
            self.clear_presence("telemetry unavailable")
        self.disconnect_rpc()

    @staticmethod
    def _classify_state(state):
        if state["in_map"] and state["in_match"]:
            return "match"
        if state["is_in_vehicle"] and state["in_map"]:
            return "test_drive"
        return "hangar"

    def _handle_live_state(self, state):
        self.last_good_state = state
        self.last_telemetry_ok_at = self.now()
        self._clear_log_once("game_missing", "telemetry_gap", "loading_transition")
        self._set_runtime_state(self._classify_state(state))
        self._publish_presence(self.build_presence_data(state))

    def tick(self):
        if not self.check_process_running():
            self._handle_game_not_running()
            return self.options.idle_interval

        state = self.get_game_state()
        if state is None:
            self._handle_telemetry_gap()
            return self.options.active_interval

        self._handle_live_state(state)
        return self.options.active_interval

    def run_forever(self):
        while not self.stop_requested():
            try:
                delay = self.tick()
            except Exception as exc:
                self.logger.error("Error updating presence: %s", exc)
                delay = self.options.active_interval

            if delay > 0 and not self.stop_requested():
                self.options.sleep_provider(delay)

        if self.options.clear_presence_on_game_exit:
            self.clear_presence("shutdown")
        self.disconnect_rpc()
