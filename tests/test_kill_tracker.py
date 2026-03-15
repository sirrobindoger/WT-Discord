import unittest

from kill_tracker import KillTracker, PlayerIdentity, parse_damage_message
from user_config import normalize_username


class NormalizeUsernameTests(unittest.TestCase):
    def test_plain_name_normalizes(self):
        self.assertEqual(normalize_username("UserName"), "username")

    def test_clan_tag_is_removed(self):
        self.assertEqual(normalize_username("[CLAN] UserName"), "username")

    def test_multiple_clan_tags_are_removed(self):
        self.assertEqual(normalize_username("[A][B] UserName"), "username")

    def test_partial_names_do_not_match(self):
        identity = PlayerIdentity("User")
        self.assertFalse(identity.matches("UserName"))


class ParseDamageMessageTests(unittest.TestCase):
    def test_destroyed_message_is_parsed(self):
        parsed = parse_damage_message("A Player (Tank) destroyed B Player (Jet)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.actor.name, "A Player")
        self.assertEqual(parsed.actor.vehicle, "Tank")
        self.assertEqual(parsed.verb, "destroyed")
        self.assertEqual(parsed.target.name, "B Player")
        self.assertEqual(parsed.target.vehicle, "Jet")

    def test_shot_down_message_is_parsed(self):
        parsed = parse_damage_message("A Player (SAM) shot down B Player (Plane)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.verb, "shot down")

    def test_non_kill_message_is_ignored(self):
        self.assertIsNone(parse_damage_message("A Player (Tank) set afire B Player (Jet)"))

    def test_ai_target_without_vehicle_is_parsed(self):
        parsed = parse_damage_message("A Player (Jet) destroyed su_r_73")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.target.name, "su_r_73")
        self.assertIsNone(parsed.target.vehicle)


class KillTrackerTests(unittest.TestCase):
    def test_actor_kill_counts_for_player(self):
        tracker = KillTracker(PlayerIdentity("_MAGNIFICENT_"))
        tracker.start_session(seed_damage_id=100)
        tracker.ingest_damage_messages([
            {"id": 101, "msg": "[KPAX] _MAGNIFICENT_ (BMPT-72) destroyed Enemy (Tank)"}
        ])
        self.assertEqual(tracker.kill_count, 1)

    def test_target_death_does_not_count(self):
        tracker = KillTracker(PlayerIdentity("_MAGNIFICENT_"))
        tracker.start_session(seed_damage_id=100)
        tracker.ingest_damage_messages([
            {"id": 101, "msg": "Enemy (Tank) destroyed [KPAX] _MAGNIFICENT_ (BMPT-72)"}
        ])
        self.assertEqual(tracker.kill_count, 0)

    def test_duplicate_damage_ids_do_not_double_count(self):
        tracker = KillTracker(PlayerIdentity("A Player"))
        tracker.start_session()
        payload = {"id": 10, "msg": "A Player (Tank) destroyed Enemy (Tank)"}
        tracker.ingest_damage_messages([payload, payload])
        tracker.ingest_damage_messages([payload])
        self.assertEqual(tracker.kill_count, 1)

    def test_non_kill_lines_do_not_count(self):
        tracker = KillTracker(PlayerIdentity("A Player"))
        tracker.start_session()
        tracker.ingest_damage_messages([
            {"id": 1, "msg": "A Player (Tank) set afire Enemy (Tank)"},
            {"id": 2, "msg": "A Player has disconnected from the game."},
        ])
        self.assertEqual(tracker.kill_count, 0)

    def test_ai_target_kill_counts(self):
        tracker = KillTracker(PlayerIdentity("A Player"))
        tracker.start_session()
        tracker.ingest_damage_messages([
            {"id": 1, "msg": "A Player (Jet) destroyed su_r_73"}
        ])
        self.assertEqual(tracker.kill_count, 1)

    def test_reset_clears_match_session(self):
        tracker = KillTracker(PlayerIdentity("A Player"))
        tracker.start_session()
        tracker.ingest_damage_messages([
            {"id": 1, "msg": "A Player (Tank) destroyed Enemy (Tank)"}
        ])
        tracker.reset_session()
        self.assertEqual(tracker.kill_count, 0)
        self.assertFalse(tracker.session_active)

    def test_session_can_start_from_latest_damage_id(self):
        tracker = KillTracker(PlayerIdentity("A Player"))
        tracker.start_session(seed_damage_id=50)
        self.assertEqual(tracker.last_damage_id, 50)


if __name__ == "__main__":
    unittest.main()
