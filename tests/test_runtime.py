import logging
import unittest
from unittest.mock import patch

from warthunder_rpc.runtime import RuntimeOptions, WarThunderRPCApp
from warthunder_rpc.windows_service import WarThunderRPCService


class FakeClock:
    def __init__(self, start=100.0):
        self.current = float(start)

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.current += float(seconds)

    def advance(self, seconds):
        self.current += float(seconds)


class FakeRPC:
    def __init__(self, fail_connect=False, fail_update=False, fail_clear=False):
        self.fail_connect = fail_connect
        self.fail_update = fail_update
        self.fail_clear = fail_clear
        self.connect_calls = 0
        self.update_calls = []
        self.clear_calls = 0
        self.close_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self.fail_connect:
            raise RuntimeError("discord closed")

    def update(self, **payload):
        if self.fail_update:
            raise RuntimeError("discord lost")
        self.update_calls.append(payload)

    def clear(self):
        self.clear_calls += 1
        if self.fail_clear:
            raise RuntimeError("clear failed")

    def close(self):
        self.close_calls += 1


class FakeRPCFactory:
    def __init__(self, *rpcs):
        self.rpcs = list(rpcs)
        self.instances = []

    def __call__(self, _client_id):
        if not self.rpcs:
            raise AssertionError("No fake RPC instance available")
        rpc = self.rpcs.pop(0)
        self.instances.append(rpc)
        return rpc


def sample_state():
    return {
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
            player_name="Pilot",
        )

        self.assertEqual(app.tick(), 17)
        self.assertEqual(app.runtime_state, "game_not_running")

    def test_local_mode_no_longer_raises_when_indicators_unavailable(self):
        app = WarThunderRPCApp(
            RuntimeOptions(mode="local", prompt_for_username=False, check_process_running=lambda: True),
            player_name="Pilot",
        )
        with patch("warthunder_rpc.runtime.requests.get", side_effect=RuntimeError("boom")):
            self.assertIsNone(app.get_json_data("indicators"))

    def test_game_exit_clears_presence_and_keeps_waiting(self):
        clock = FakeClock()
        rpc = FakeRPC()
        app = WarThunderRPCApp(
            RuntimeOptions(
                prompt_for_username=False,
                check_process_running=lambda: True,
                time_provider=clock.now,
                sleep_provider=clock.sleep,
            ),
            player_name="Pilot",
            rpc_factory=FakeRPCFactory(rpc),
        )
        app.get_game_state = lambda: sample_state()
        app.tick()

        app.check_process_running = lambda: False
        delay = app.tick()

        self.assertEqual(delay, app.options.idle_interval)
        self.assertEqual(app.runtime_state, "game_not_running")
        self.assertEqual(rpc.clear_calls, 1)
        self.assertGreaterEqual(rpc.close_calls, 1)

    def test_loading_gap_preserves_last_presence_during_grace_period(self):
        clock = FakeClock()
        rpc = FakeRPC()
        app = WarThunderRPCApp(
            RuntimeOptions(
                prompt_for_username=False,
                check_process_running=lambda: True,
                telemetry_grace_seconds=20,
                time_provider=clock.now,
                sleep_provider=clock.sleep,
            ),
            player_name="Pilot",
            rpc_factory=FakeRPCFactory(rpc),
        )
        states = iter([sample_state(), None])
        app.get_game_state = lambda: next(states)

        app.tick()
        clock.advance(5)
        app.tick()

        self.assertEqual(app.runtime_state, "loading_transition")
        self.assertEqual(rpc.clear_calls, 0)
        self.assertTrue(app.presence_active)

    def test_long_telemetry_gap_clears_presence(self):
        clock = FakeClock()
        rpc = FakeRPC()
        app = WarThunderRPCApp(
            RuntimeOptions(
                prompt_for_username=False,
                check_process_running=lambda: True,
                telemetry_grace_seconds=5,
                time_provider=clock.now,
                sleep_provider=clock.sleep,
            ),
            player_name="Pilot",
            rpc_factory=FakeRPCFactory(rpc),
        )
        app.get_game_state = lambda: sample_state()
        app.tick()

        app.get_game_state = lambda: None
        clock.advance(10)
        app.tick()

        self.assertEqual(app.runtime_state, "telemetry_unavailable")
        self.assertEqual(rpc.clear_calls, 1)

    def test_discord_not_running_is_retried_without_crashing(self):
        clock = FakeClock()
        failing_rpc = FakeRPC(fail_connect=True)
        app = WarThunderRPCApp(
            RuntimeOptions(
                prompt_for_username=False,
                check_process_running=lambda: True,
                rpc_retry_interval=5,
                time_provider=clock.now,
                sleep_provider=clock.sleep,
            ),
            player_name="Pilot",
            rpc_factory=FakeRPCFactory(failing_rpc),
        )
        app.get_game_state = lambda: sample_state()

        delay = app.tick()

        self.assertEqual(delay, app.options.active_interval)
        self.assertEqual(app.runtime_state, "discord_unavailable")
        self.assertIsNotNone(app.last_presence_payload)

    def test_discord_reconnect_publishes_cached_state(self):
        clock = FakeClock()
        failing_rpc = FakeRPC(fail_connect=True)
        working_rpc = FakeRPC()
        app = WarThunderRPCApp(
            RuntimeOptions(
                prompt_for_username=False,
                check_process_running=lambda: True,
                rpc_retry_interval=5,
                time_provider=clock.now,
                sleep_provider=clock.sleep,
            ),
            player_name="Pilot",
            rpc_factory=FakeRPCFactory(failing_rpc, working_rpc),
        )
        app.get_game_state = lambda: sample_state()

        app.tick()
        clock.advance(6)
        app.tick()

        self.assertEqual(app.runtime_state, "match")
        self.assertEqual(len(working_rpc.update_calls), 1)
        self.assertTrue(app.presence_active)

    def test_discord_drop_mid_session_recovers_after_backoff(self):
        clock = FakeClock()
        first_rpc = FakeRPC(fail_update=True)
        second_rpc = FakeRPC()
        app = WarThunderRPCApp(
            RuntimeOptions(
                prompt_for_username=False,
                check_process_running=lambda: True,
                rpc_retry_interval=5,
                time_provider=clock.now,
                sleep_provider=clock.sleep,
            ),
            player_name="Pilot",
            rpc_factory=FakeRPCFactory(first_rpc, second_rpc),
        )
        app.get_game_state = lambda: sample_state()

        app.tick()
        self.assertEqual(app.runtime_state, "discord_unavailable")

        clock.advance(6)
        app.tick()

        self.assertEqual(app.runtime_state, "match")
        self.assertEqual(len(second_rpc.update_calls), 1)

    def test_kill_tracker_resets_only_after_confirmed_game_exit(self):
        clock = FakeClock()
        rpc = FakeRPC()
        app = WarThunderRPCApp(
            RuntimeOptions(
                prompt_for_username=False,
                check_process_running=lambda: True,
                telemetry_grace_seconds=20,
                time_provider=clock.now,
                sleep_provider=clock.sleep,
            ),
            player_name="Pilot",
            rpc_factory=FakeRPCFactory(rpc),
        )
        app.kill_tracker.start_session(seed_damage_id=10)
        app.kill_tracker.kill_count = 3
        app.last_good_state = sample_state()
        app.last_presence_payload = app.build_presence_data(sample_state())
        app.last_telemetry_ok_at = clock.now()

        app._handle_telemetry_gap()
        self.assertTrue(app.kill_tracker.session_active)
        self.assertEqual(app.kill_tracker.kill_count, 3)

        app.check_process_running = lambda: False
        app.tick()
        self.assertFalse(app.kill_tracker.session_active)
        self.assertEqual(app.kill_tracker.kill_count, 0)


class PresencePayloadTests(unittest.TestCase):
    def test_match_payload_prefers_vehicle_image(self):
        app = WarThunderRPCApp(RuntimeOptions(mode="local", prompt_for_username=False), player_name="Pilot")
        app.clock_timer = 123

        payload = app.build_presence_data(sample_state())

        self.assertEqual(payload["large_image"], "https://example.com/m1.png")
        self.assertEqual(payload["large_text"], "Kursk")
        self.assertEqual(payload["details"], "Ground Battle, 2 Kills")


class ServiceSupervisionTests(unittest.TestCase):
    def test_service_launches_worker_task_when_worker_missing(self):
        with patch("warthunder_rpc.windows_service.build_service_logger", return_value=logging.getLogger("test.service")):
            service = WarThunderRPCService(None)
            service.is_worker_running = lambda: False
            launches = []
            service.launch_worker = lambda: launches.append("run") or True

            delay = service.supervise_worker()

            self.assertEqual(delay, service.idle_check_interval)
            self.assertEqual(launches, ["run"])

    def test_service_skips_launch_when_worker_is_already_running(self):
        with patch("warthunder_rpc.windows_service.build_service_logger", return_value=logging.getLogger("test.service")):
            service = WarThunderRPCService(None)
            service.is_worker_running = lambda: True
            launches = []
            service.launch_worker = lambda: launches.append("run") or True

            delay = service.supervise_worker()

            self.assertEqual(delay, service.check_interval)
            self.assertEqual(launches, [])


if __name__ == "__main__":
    unittest.main()
