import requests
import urllib.request
import json
import time
from PIL import Image
from pypresence import Presence
import telemetry
import tkinter as tk
from tkinter import simpledialog
import winreg
import re
from vehicle_images import VehicleImageResolver


DEFAULT_LARGE_IMAGE_URL = "https://warthunder.com/assets/img/svg/logo-wt.svg"


class WarThunderRPC:
    def __init__(self):
        self.client_id = "1211769535468937237"
        self.rpc = Presence(self.client_id)
        self.rpc.connect()
        self.clock_timer = int(time.time())
        self.base_url = "http://127.0.0.1:8111"
        self.player_name = self.get_warthunder_username()
        self.kill_count = 0
        self.last_evt, self.last_dmg = self.initialize_hudmsg_ids()
        self.current_match_id = None  # To track match changes
        self.image_resolver = VehicleImageResolver()

    def get_warthunder_username(self):
        try:
            registry_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\WarThunderRPC", 0, winreg.KEY_READ)
            player_name, _ = winreg.QueryValueEx(registry_key, "Username")
            winreg.CloseKey(registry_key)
            if player_name:
                return player_name
        except FileNotFoundError:
            pass
        return self.prompt_get_warthunder_username()

    def prompt_get_warthunder_username(self):
        root = tk.Tk()
        root.withdraw()  # Hide the root window
        player_name = simpledialog.askstring("War Thunder Username", "What is your War Thunder username?")
        if player_name:
            registry_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\WarThunderRPC")
            winreg.SetValueEx(registry_key, "Username", 0, winreg.REG_SZ, player_name)
            winreg.CloseKey(registry_key)
        return player_name

    def parse_country(self, tank_name):
        """Parse country code from tank name with special cases"""
        if not tank_name or tank_name == "Unknown":
            return "US"
            
        parts = tank_name.split(" ")
        if not parts:
            return "US"
            
        country_code = parts[0].upper()
        
        # Special case mappings
        country_mapping = {
            "GERM": "DE",
            "USSR": "RU",
            "UK": "GB",
            "SW": "SE"
        }
        
        return country_mapping.get(country_code, country_code)
        
    def initialize_hudmsg_ids(self):
        data, _ = self.fetch_hudmsg(0, 0)
        if data:
            last_dmg = data[-1]['id']
        else:
            last_dmg = 0
        return 0, last_dmg

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

    def update_kill_count(self):
        damage_msgs, _ = self.fetch_hudmsg(self.last_evt, self.last_dmg)
        if damage_msgs:
            self.last_dmg = damage_msgs[-1]['id']
            for dmg in damage_msgs:
                msg = dmg.get('msg', '').lower()
                if self.player_name.lower() in msg and "destroyed" in msg and not ("destroyed " + self.player_name.lower()) in msg:
                    self.kill_count += 1

    def get_game_state(self):
        indicators = self.get_json_data("indicators")
        mission = self.get_json_data("mission.json")
        map_info = self.get_json_data("map_info.json")
        raw_vehicle_type = indicators.get("type", "Unknown")
        vehicle_slug = self.image_resolver.extract_vehicle_slug(raw_vehicle_type)
        vehicle_name = self.image_resolver.format_vehicle_name(vehicle_slug)
        
        
        # Update kill count
        self.update_kill_count()
        
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
            "kill_count": self.kill_count,
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
            "large_image": DEFAULT_LARGE_IMAGE_URL,
            "large_text": "War Thunder"
        }

        if not state["in_map"]:
            # reset kill count if it's > 0
            if self.kill_count > 0:
                self.kill_count = 0
            return {**base_presence, "state": "In the hangar", "details": "Browsing vehicles.."}

        # Only add country flag for tanks, not planes
        is_tank = state["vehicle_type"] == "tank"
        if is_tank:
            country_code = self.parse_country(state['vehicle_name'])
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
                    "large_image": state["vehicle_image_url"] or base_presence["large_image"]}

        if state["is_in_vehicle"] and state["in_map"] and state["in_match"]:
            action = "Piloting" if state["vehicle_type"] == "air" else "Driving"
            match_type = self.get_match_type(state["main_objective"], state["vehicle_type"])
            status_text = f"{match_type} | {state['team_status']} | {state['kill_count']} Targets"
            
            return {**base_presence,
                "state": f"{action} a {state['vehicle_name'].upper()}, {state['health_status']}",
                "details": status_text,
                "large_image": state["vehicle_image_url"] or base_presence["large_image"],
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
