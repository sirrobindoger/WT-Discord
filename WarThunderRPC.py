import requests
import urllib.request
import json
import time
import os
from PIL import Image
from pypresence import Presence
import telemetry
import re
from vehicle_images import VehicleImageResolver
from kill_tracker import KillTracker, PlayerIdentity
from user_config import get_or_prompt_username


DEFAULT_LARGE_IMAGE = (
    os.getenv("WARTHUNDER_RPC_LARGE_IMAGE", "https://unixcore.sh/wt1.webp")
    or os.getenv("WARTHUNDER_RPC_LARGE_IMAGE_KEY", "wt-logo")
).strip()


class WarThunderRPC:
    def __init__(self):
        self.client_id = "1211769535468937237"
        self.rpc = Presence(self.client_id)
        self.rpc.connect()
        self.clock_timer = int(time.time())
        self.base_url = "http://127.0.0.1:8111"
        self.player_name = get_or_prompt_username(prompt_if_missing=True)
        self.kill_tracker = KillTracker(PlayerIdentity(self.player_name))
        self.current_match_id = None  # To track match changes
        self.image_resolver = VehicleImageResolver()

    def fetch_hudmsg(self, last_evt=0, last_dmg=0):
        try:
            response = requests.get(f"{self.base_url}/hudmsg?lastEvt={last_evt}&lastDmg={last_dmg}")
            response.raise_for_status()
            data = response.json()
            return data['damage'], data['events']
        except Exception as e:
            print(f"Error fetching hudmsg: {e}")
            return [], []

    def get_map_obj_info(self):
        try:
            response = requests.get(f"{self.base_url}/map_obj.json")
            data = response.json()
            
            friendly_zones = 0
            enemy_zones = 0

            for obj in data:
                if obj.get('type') == 'capture_zone':
                    color = obj.get('color')
                    if color == "#174DFF":  # Friendly (Blue)
                        friendly_zones += 1
                    elif color == "#fa0C00":  # Enemy (Red)
                        enemy_zones += 1

            if friendly_zones > enemy_zones:
                return "Winning"
            elif friendly_zones < enemy_zones:
                return "Losing"
            return "Tied"
        except Exception as e:
            print(f"Error fetching map objects: {e}")
            return "Unknown"

    def get_match_type(self, objective, vehicle_type):
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
            "Prevent the capture of the allied point": "Battle"
        }
        
        base_type = "Ground" if vehicle_type == "tank" else "Air"
        match_type = objective_mapping.get(objective, "Operations")
        
        if base_type == "Air" and match_type in ["Battle", "Domination", "Conquest"]:
            return f"Ground {match_type}"
        elif base_type == "Air":
            return f"Air {match_type}"
        return f"Ground {match_type}"

    def get_json_data(self, endpoint):
        try:
            response = requests.get(f"{self.base_url}/{endpoint}")
            return json.loads(response.text)
        except:
            if endpoint == "indicators":
                print("War Thunder is not running, or port 8111 is already occupied!")
                time.sleep(1)
                print("Exiting...")
                time.sleep(4)
                exit()
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

    def get_game_state(self):
        indicators = self.get_json_data("indicators")
        mission = self.get_json_data("mission.json")
        map_info = self.get_json_data("map_info.json")
        raw_vehicle_type = indicators.get("type", "Unknown")
        vehicle_slug = self.image_resolver.extract_vehicle_slug(raw_vehicle_type)
        vehicle_name = self.image_resolver.get_display_name(vehicle_slug)
        
        # Calculate health status
        crew_current = str(indicators.get("crew_current") )
        crew_total = str(indicators.get("crew_total", 1))  # Default to 1 to avoid division by zero
        
        health_status = crew_current[:-2] + "/" + crew_total[:-2] + " Crew" 
        
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
            "health_status": health_status
        }
        
        if mission and "objectives" in mission and mission["objectives"]:
            # replace all special characters and trim the string
            raw_objective = mission["objectives"][0].get("text", "false")
            cleaned_objective = re.sub(r'[^\w\s]', '', raw_objective).strip()
            print(cleaned_objective)
            state["main_objective"] = cleaned_objective
            state["in_match"] = mission["objectives"][0].get("primary", False)

        self.update_kill_count(state["in_map"] and state["in_match"])
        state["kill_count"] = self.kill_tracker.kill_count
        
        if state["in_map"] and state["in_match"]:
            state["team_status"] = self.get_map_obj_info()
        
        if state["in_map"]:
            urllib.request.urlretrieve(f"{self.base_url}/map.img", "map.jpg")
            img = Image.open("map.jpg")
            map_data = telemetry.mapinfo.get_grid_info(map_img=img)
            state["current_map"] = map_data["name"].replace("_", " ")

            if state["vehicle_slug"] != "DUMMY_PLANE":
                state["vehicle_image_url"], state["vehicle_image_status"] = self.image_resolver.resolve(state["vehicle_slug"])
            
        return state

    def build_presence_data(self, state):
        base_presence = {
            "start": self.clock_timer,
            "large_text": "War Thunder"
        }
        if DEFAULT_LARGE_IMAGE:
            # Discord accepts either an uploaded asset key or an external image URL here.
            base_presence["large_image"] = DEFAULT_LARGE_IMAGE
        fallback_large_image = base_presence.get("large_image")

        if not state["in_map"]:
            return {**base_presence, "state": "In the hangar", "details": "Browsing vehicles.."}

        # Only add country flag for tanks, not planes
        is_tank = state["vehicle_type"] == "tank"
        if is_tank:
            country_code = self.image_resolver.get_country_code(state["vehicle_slug"])
            base_presence.update({
                "small_image": f"https://flagsapi.com/{country_code}/flat/64.png",
                "small_text": country_code
            })
        
        if state["is_in_vehicle"] and state["in_map"] and not state["in_match"]:
            action = "Piloting" if state["vehicle_type"] == "air" else "Driving"
            
            if state["vehicle_name"] == "DUMMY PLANE":
                return {**base_presence, "state": "Loading into a match..", 
                    "details": f"{state['vehicle_type'].capitalize()} Match"}
            else:
                return {**base_presence, 
                    "state": f"{action} a {state['vehicle_name'].upper()}", 
                    "details": f"In Test Drive | {state['health_status']}",
                    **({"large_image": state["vehicle_image_url"] or fallback_large_image} if state["vehicle_image_url"] or fallback_large_image else {})}

        if state["is_in_vehicle"] and state["in_map"] and state["in_match"]:
            action = "Piloting" if state["vehicle_type"] == "air" else "Driving"
            match_type = self.get_match_type(state["main_objective"], state["vehicle_type"])
            status_text = f"{match_type} | {state['kill_count']} Kills"
            
            return {**base_presence,
                "state": f"{action} a {state['vehicle_name'].upper()}, {state['health_status']}",
                "details": status_text,
                **({"large_image": state["vehicle_image_url"] or fallback_large_image} if state["vehicle_image_url"] or fallback_large_image else {}),
                "large_text": state["current_map"]
                }

        return {**base_presence, "state": "Unknown vehicle", "details": "In-game"}

    def update_presence(self):
        while True:
            try:
                state = self.get_game_state()
                presence_data = self.build_presence_data(state)
                self.rpc.update(**presence_data)
                print(f"Updated presence: {presence_data}")
                time.sleep(3)
            except Exception as e:
                print(f"Error updating presence: {e}")
                time.sleep(3)

if __name__ == "__main__":
    wt_rpc = WarThunderRPC()
    wt_rpc.update_presence()
