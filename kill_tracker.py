from dataclasses import dataclass

from user_config import normalize_username


KILL_VERBS = ("destroyed", "shot down")


@dataclass(frozen=True)
class Participant:
    name: str
    vehicle: str | None = None


@dataclass(frozen=True)
class ParsedKillEvent:
    actor: Participant
    verb: str
    target: Participant


class PlayerIdentity:
    def __init__(self, raw_username):
        self.raw_username = (raw_username or "").strip()
        self.normalized_username = normalize_username(self.raw_username)

    def is_configured(self):
        return bool(self.normalized_username)

    def matches(self, candidate_name):
        if not self.normalized_username:
            return False
        return normalize_username(candidate_name) == self.normalized_username


def parse_participant(segment):
    segment = " ".join((segment or "").strip().split())
    if not segment:
        return Participant(name="")

    if segment.endswith(")") and " (" in segment:
        name, vehicle = segment.split(" (", 1)
        return Participant(name=name.strip(), vehicle=vehicle[:-1].strip())

    return Participant(name=segment)


def parse_damage_message(message):
    message = " ".join((message or "").strip().split())
    if not message:
        return None

    matches = []
    for verb in KILL_VERBS:
        marker = f" {verb} "
        index = message.find(marker)
        if index != -1:
            matches.append((index, verb, marker))

    if not matches:
        return None

    index, verb, marker = min(matches, key=lambda item: item[0])
    actor_segment = message[:index].strip()
    target_segment = message[index + len(marker):].strip()
    actor = parse_participant(actor_segment)
    target = parse_participant(target_segment)

    if not actor.name or not target.name:
        return None

    return ParsedKillEvent(actor=actor, verb=verb, target=target)


class KillTracker:
    def __init__(self, player_identity):
        self.player_identity = player_identity
        self.kill_count = 0
        self.session_active = False
        self.last_damage_id = 0
        self.seen_damage_ids = set()

    def start_session(self, seed_damage_id=0):
        self.session_active = True
        self.kill_count = 0
        self.last_damage_id = seed_damage_id or 0
        self.seen_damage_ids = set()

    def reset_session(self):
        self.session_active = False
        self.kill_count = 0
        self.seen_damage_ids = set()

    def ingest_damage_messages(self, damage_messages):
        if not self.session_active:
            return self.kill_count

        latest_damage_id = self.last_damage_id
        for damage_message in damage_messages or []:
            damage_id = int(damage_message.get("id", 0))
            latest_damage_id = max(latest_damage_id, damage_id)
            if damage_id in self.seen_damage_ids:
                continue

            self.seen_damage_ids.add(damage_id)
            parsed_event = parse_damage_message(damage_message.get("msg", ""))
            if not parsed_event:
                continue

            if self.player_identity.matches(parsed_event.target.name):
                continue

            if self.player_identity.matches(parsed_event.actor.name):
                self.kill_count += 1

        self.last_damage_id = latest_damage_id
        return self.kill_count

    @staticmethod
    def latest_damage_id(damage_messages):
        return max((int(message.get("id", 0)) for message in damage_messages or []), default=0)
