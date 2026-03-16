from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

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
        self.clock_timer = int(time.time())
        self.base_url = "http://127.0.0.1:8111"
        self.check_process_running = self.options.check_process_running
        self.stop_requested = self.options.stop_requested or (lambda: False)
        self.image_resolver = VehicleImageResolver(logger=self.logger)

        if player_name is None:
            if self.options.prompt_for_username:
                player_name = get_or_prompt_username(prompt_if_missing=True)
            else:
                player_name = read_username()

        self.player_name = player_name
        self.kill_tracker = KillTracker(PlayerIdentity(self.player_name))

    def connect_rpc(self):
        if self.rpc is not None:
            return

        self.rpc = self.rpc_factory(self.client_id)
        self.rpc.connect()
        self.clock_timer = int(time.time())

    def disconnect_rpc(self):
        if self.rpc is None:
            return

        try:
            self.rpc.close()
        finally:
            self.rpc = None

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
            if endpoint == "indicators" and self.options.mode == "local":
                raise RuntimeError(
                    "War Thunder is not running, or port 8111 is already occupied!"
                ) from exc
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

    def tick(self):
        if self.check_process_running and not self.check_process_running():
            self.disconnect_rpc()
            return self.options.idle_interval

        self.connect_rpc()
        state = self.get_game_state()
        if state is None:
            return self.options.active_interval

        presence_data = self.build_presence_data(state)
        self.rpc.update(**presence_data)
        self.logger.info("Updated presence: %s", presence_data)
        return self.options.active_interval

    def run_forever(self):
        while not self.stop_requested():
            try:
                delay = self.tick()
            except RuntimeError as exc:
                if self.options.mode == "local":
                    print(str(exc))
                    time.sleep(1)
                    print("Exiting...")
                    time.sleep(4)
                    break
                self.logger.error("Runtime error: %s", exc)
                delay = self.options.idle_interval
            except Exception as exc:
                self.logger.error("Error updating presence: %s", exc)
                delay = self.options.active_interval

            if delay > 0 and not self.stop_requested():
                time.sleep(delay)

        self.disconnect_rpc()
