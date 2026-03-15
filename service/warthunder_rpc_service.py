# warthunder_rpc_service.py
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import os
import requests
import json
from pypresence import Presence
import telemetry
from PIL import Image
import urllib.request
import re
import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import asyncio
import nest_asyncio
import threading
import psutil

PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from vehicle_images import VehicleImageResolver
from kill_tracker import KillTracker, PlayerIdentity
from user_config import read_username


log_dir = os.path.join(os.environ.get("PROGRAMDATA"), "WarThunderRPC")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,  # Set the logging level
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Define the log format
    handlers=[
        # log to PROGRAMDATA/WarThunderRPC/WarThunderRPC.log
        logging.FileHandler(os.path.join(os.environ.get("PROGRAMDATA"), "WarThunderRPC", "WarThunderRPC.log")),
        logging.StreamHandler()  # Also log to console
    ]
)

class WarThunderRPCService(win32serviceutil.ServiceFramework):
    _svc_name_ = "WarThunderRPC"
    _svc_display_name_ = "War Thunder Discord Rich Presence"
    _svc_description_ = "Provides Discord Rich Presence integration for War Thunder"

    def __init__(self, args):
        if args is not None:
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            socket.setdefaulttimeout(60)
            self.is_running_as_service = True
        else:
            self.stop_event = None
            self.is_running_as_service = False

        self.logger = logging.getLogger(__name__)
        self.client_id = "1211769535468937237"
        self.rpc = None
        self.clock_timer = int(time.time())
        self.base_url = "http://127.0.0.1:8111"
        self.player_name = read_username()
        self.kill_tracker = KillTracker(PlayerIdentity(self.player_name))
        self.current_match_id = None
        self.game_running = False
        self.check_interval = 3
        self.idle_check_interval = 10  # Changed from 60 to 10 seconds
        self.loop = None
        self.rpc_thread = None
        self.image_resolver = VehicleImageResolver(logger=self.logger)
        
        self.logger.info(f"Service initialized. Running as service: {self.is_running_as_service}")

    def setup_asyncio(self):
        """Set up asyncio event loop in a separate thread"""
        def run_event_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            nest_asyncio.apply(self.loop)
            self.loop.run_forever()

        self.rpc_thread = threading.Thread(target=run_event_loop, daemon=True)
        self.rpc_thread.start()

    def connect_rpc(self):
        try:
            if self.rpc is None:
                if self.loop is None:
                    self.setup_asyncio()
                
                # Create and connect RPC in the event loop
                future = asyncio.run_coroutine_threadsafe(self._async_connect_rpc(), self.loop)
                future.result(timeout=10)  # Wait for connection with timeout
                self.logger.info("Connected to Discord RPC")
                #reset self.clock_timer
                self.clock_timer = int(time.time())
        except Exception as e:
            self.logger.error(f"Failed to connect to Discord RPC: {e}")
            self.rpc = None

    async def _async_connect_rpc(self):
        """Async helper for RPC connection"""
        self.rpc = Presence(self.client_id)
        await self.loop.run_in_executor(None, self.rpc.connect)

    def disconnect_rpc(self):
        try:
            if self.rpc:
                if self.loop:
                    future = asyncio.run_coroutine_threadsafe(self._async_disconnect_rpc(), self.loop)
                    future.result(timeout=10)
                self.rpc = None
                self.logger.info("Disconnected from Discord RPC")
        except Exception as e:
            self.logger.error(f"Error disconnecting RPC: {e}")

    async def _async_disconnect_rpc(self):
        """Async helper for RPC disconnection"""
        await self.loop.run_in_executor(None, self.rpc.close)


    def SvcStop(self):
        if self.is_running_as_service:
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
        
        if self.rpc:
            self.disconnect_rpc()
        
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
            if self.rpc_thread:
                self.rpc_thread.join(timeout=5)
        
        self.logger.info("Service stopped")


    def SvcDoRun(self):
        """
        Called when the service is starting. Main service entry point.
        """
        try:
            self.logger.info("Service starting...")
            
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
           servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, '')
            )
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            self.run_service()
        except Exception as e:
            self.logger.error(f"Service failed: {e}")
            servicemanager.LogErrorMsg(f"Service failed: {str(e)}")

    def should_stop(self):
        """
        Check if the service should stop
        """
        if self.is_running_as_service:
            # Check for service stop signal
            return win32event.WaitForSingleObject(self.stop_event, 1000) == win32event.WAIT_OBJECT_0
        else:
            return False

    def run_service(self):
        self.logger.info("Starting main service loop")
        try:
            while not self.should_stop():
                try:
                    if self.check_game_running():
                        if not self.rpc:
                            self.connect_rpc()
                        self.update_presence()
                        time.sleep(self.check_interval)
                    else:
                        if self.rpc:
                            self.disconnect_rpc()
                        time.sleep(self.idle_check_interval)
                except Exception as e:
                    self.logger.error(f"Error in service loop: {e}")
                    time.sleep(self.idle_check_interval)
        except KeyboardInterrupt:
            self.logger.info("KeyboardInterrupt received, stopping service")
        finally:
            self.SvcStop()

    def disconnect_rpc(self):
        try:
            if self.rpc:
                self.rpc.close()
                self.rpc = None
                self.logger.info("Disconnected from Discord RPC")
        except Exception as e:
            self.logger.error(f"Error disconnecting RPC: {e}")

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
        raw_state = self.get_json_data("state")
        raw_vehicle_type = indicators.get("type", "Unknown")
        vehicle_slug = self.image_resolver.extract_vehicle_slug(raw_vehicle_type)
        vehicle_name = self.image_resolver.get_display_name(vehicle_slug)
        
        # Calculate health status
        crew_current = str(indicators.get("crew_current") )
        crew_total = str(indicators.get("crew_total", 1))  # Default to 1 to avoid division by zero
        
       

        # if the vehicle is air, then instead get its speed and altitude
        if indicators.get("army") == "air":
            # get "TAS, km/h" and "H, m" from indicators
            speed = str(raw_state.get("TAS, km/h", 0))
            altitude = str(raw_state.get("H, m", 0))
            health_status = f"{speed} km/h | {altitude} m"
        else:
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
            "large_image": "logo",
            "large_text": "War Thunder"
        }

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
                    "large_image": state["vehicle_image_url"] or base_presence["large_image"]}

        if state["is_in_vehicle"] and state["in_map"] and state["in_match"]:
            action = "Piloting" if state["vehicle_type"] == "air" else "Driving"
            match_type = self.get_match_type(state["main_objective"], state["vehicle_type"])
            status_text = f"{match_type} | {state['kill_count']} Kills"
            
            return {**base_presence,
                "state": f"{action} a {state['vehicle_name'].upper()}, {state['health_status']}",
                "details": status_text,
                "large_image": state["vehicle_image_url"] or base_presence["large_image"],
                "large_text": state["current_map"]
                }

        return {**base_presence, "state": "Unknown vehicle", "details": "In-game"}

    def update_presence(self):
        if not self.rpc:
            return
            
        try:
            state = self.get_game_state()
            presence_data = self.build_presence_data(state)
            
            # Update presence through the event loop
            if self.loop:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_update_presence(presence_data),
                    self.loop
                )
                future.result(timeout=5)
        except Exception as e:
            self.logger.error(f"Error updating presence: {e}")

    async def _async_update_presence(self, presence_data):
        """Async helper for presence updates"""
        await self.loop.run_in_executor(None, lambda: self.rpc.update(**presence_data))

    def is_aces_running(self):
        """Check if aces.exe is running"""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'].lower() == 'aces.exe':
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return False

    def check_game_running(self):
        """
        Check if War Thunder is running by first checking for aces.exe,
        then checking if the HTTP endpoint is responsive
        """
        if not self.is_aces_running():
            if self.game_running:
                self.logger.info("War Thunder process closed - switching to idle mode")
                self.game_running = False
                self.disconnect_rpc()
            return False

        try:
            response = requests.get(f"{self.base_url}/indicators", timeout=2)
            if response.status_code == 200:
                if not self.game_running:
                    self.logger.info("War Thunder detected - switching to active mode")
                    self.game_running = True
                    self.connect_rpc()
                return True
            return True  # Return True even if endpoint isn't responsive, as long as aces.exe is running
        except:
            return True  # Return True if aces.exe is running, even during loading screens
