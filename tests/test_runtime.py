import unittest
from unittest.mock import patch

from warthunder_rpc.runtime import RuntimeOptions, WarThunderRPCApp


class RuntimeBehaviorTests(unittest.TestCase):
    def test_root_precedence_health_status_uses_crew_counts_for_air(self):
        status = WarThunderRPCApp.build_health_status(
            {
                "army": "air",
                "crew_current": 2.0,
                "crew_total": 3.0,
                "TAS, km/h": 850,
                "H, m": 1200,
            }
        )
        self.assertEqual(status, "2/3 Crew")

    def test_service_mode_short_circuits_when_process_is_not_running(self):
        app = WarThunderRPCApp(
            RuntimeOptions(
                mode="service",
                prompt_for_username=False,
                check_process_running=lambda: False,
                idle_interval=17,
            ),
            rpc_factory=lambda _: (_ for _ in ()).throw(AssertionError("RPC should not connect")),
        )

        self.assertEqual(app.tick(), 17)

    def test_local_mode_raises_friendly_error_when_indicators_unavailable(self):
        app = WarThunderRPCApp(RuntimeOptions(mode="local"), player_name="Pilot")
        with patch("warthunder_rpc.runtime.requests.get", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(RuntimeError, "War Thunder is not running"):
                app.get_json_data("indicators")


class PresencePayloadTests(unittest.TestCase):
    def test_match_payload_prefers_vehicle_image(self):
        app = WarThunderRPCApp(RuntimeOptions(mode="local"), player_name="Pilot")
        app.clock_timer = 123
        state = {
            "is_in_vehicle": True,
            "vehicle_type": "tank",
            "vehicle_slug": "us_m1a1_hc_abrams",
            "vehicle_name": "M1A1 HC",
            "vehicle_image_url": "https://example.com/m1.png",
            "vehicle_image_status": "resolved_direct",
            "in_match": True,
            "main_objective": "Capture the enemy point",
            "in_map": True,
            "current_map": "Kursk",
            "kill_count": 2,
            "team_status": "Winning",
            "health_status": "3/4 Crew",
        }

        payload = app.build_presence_data(state)

        self.assertEqual(payload["large_image"], "https://example.com/m1.png")
        self.assertEqual(payload["large_text"], "Kursk")
        self.assertEqual(payload["details"], "Ground Battle | 2 Kills")


if __name__ == "__main__":
    unittest.main()
