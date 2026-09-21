# Ashen Gate: a short dungeon where Jev and Laya make typed decisions each room.
# Same rooms, same questions — different judgment.
from __future__ import annotations

import copy
import random
import uuid
from typing import Any

# Keep a few live runs in memory so the UI can tick room by room.
_SESSIONS: dict[str, dict] = {}

START_HP = 10
ROOM_COUNT = 8


def _rooms_for_seed(seed: int) -> list[dict]:
    # Fixed sequence shape so both models face the same story arc.
    rng = random.Random(seed)
    kinds = ["monster", "trap", "merchant", "shrine", "fork", "treasure", "monster", "boss"]
    rooms = []
    for index, kind in enumerate(kinds):
        rooms.append(_make_room(kind, index, rng))
    return rooms


def _make_room(kind: str, index: int, rng: random.Random) -> dict:
    room_no = index + 1
    if kind == "monster":
        name = rng.choice(["Cave bat swarm", "Rust goblin", "Bone hound", "Mire slug"])
        strength = rng.choice([1, 2, 2, 3])
        return {
            "index": index,
            "kind": kind,
            "title": f"Room {room_no}: {name}",
            "blurb": (
                f"A {name.lower()} blocks the corridor. "
                f"It looks strength-{strength}/3. "
                "Torchlight shakes on wet stone. Your pack has a short blade and a smoke vial."
            ),
            "meta": {"strength": strength, "reward": 4 + strength},
        }
    if kind == "trap":
        return {
            "index": index,
            "kind": kind,
            "title": f"Room {room_no}: Pressure plates",
            "blurb": (
                "The floor is tiled with faint seams. A gold coin sits on the center plate. "
                "A draft from the side tunnel smells safer, but slower."
            ),
            "meta": {"bait_gold": 6, "safe_gold": 1},
        }
    if kind == "merchant":
        return {
            "index": index,
            "kind": kind,
            "title": f"Room {room_no}: Hooded merchant",
            "blurb": (
                "A merchant offers three deals: a healing salve (3 gold, +4 hp), "
                "a lucky charm (5 gold, +1 relic), or ignore him and keep moving."
            ),
            "meta": {},
        }
    if kind == "shrine":
        return {
            "index": index,
            "kind": kind,
            "title": f"Room {room_no}: Cracked shrine",
            "blurb": (
                "An old shrine hums. Kneeling may heal you, or wake a curse. "
                "Walking past is safe but earns nothing."
            ),
            "meta": {},
        }
    if kind == "fork":
        return {
            "index": index,
            "kind": kind,
            "title": f"Room {room_no}: Twin tunnels",
            "blurb": (
                "Left tunnel: loud dripping, likely a fight and better loot. "
                "Right tunnel: quiet, likely a small pouch and no blood."
            ),
            "meta": {},
        }
    if kind == "treasure":
        return {
            "index": index,
            "kind": kind,
            "title": f"Room {room_no}: Sealed chest",
            "blurb": (
                "A sealed chest has scratch marks around the lock. "
                "Opening it could mean a relic — or a spring-blade."
            ),
            "meta": {},
        }
    # boss
    return {
        "index": index,
        "kind": kind,
        "title": f"Room {room_no}: Gate warden",
        "blurb": (
            "The Ashen Gate warden waits — tall, armored, patient. "
            "You can charge, bargain with your gold, or try to slip past in the smoke."
        ),
        "meta": {"strength": 3, "reward": 12},
    }


def _new_player(name: str) -> dict:
    return {
        "name": name,
        "hp": START_HP,
        "max_hp": START_HP,
        "gold": 0,
        "relics": 0,
        "room": 0,
        "alive": True,
        "finished": False,
        "log": ["Entered the Ashen Gate."],
        "last_decision": None,
        "last_latency_ms": None,
        "score": 0,
    }


def questions_for_room(room: dict) -> dict:
    kind = room["kind"]
    if kind == "monster":
        return {
            "action": {
                "type": "choice",
                "instructions": "What should the adventurer do against this foe?",
                "criteria": {
                    "fight": "engage in open combat for loot",
                    "sneak": "slip past with some risk and less reward",
                    "flee": "retreat to a safer path, little or no loot",
                },
            },
            "danger": {
                "type": "score",
                "instructions": "How dangerous is this encounter for a tired adventurer?",
                "criteria": ["mild threat", "serious threat", "likely lethal if mishandled"],
            },
            "use_smoke": {
                "type": "noul",
                "instructions": "Should the adventurer spend their smoke vial to lower risk?",
                "criteria": {
                    "true": "use smoke to reduce damage risk",
                    "false": "save the vial and face the fight clean",
                },
            },
        }
    if kind == "trap":
        return {
            "action": {
                "type": "choice",
                "instructions": "How should the adventurer cross the trapped floor?",
                "criteria": {
                    "grab_coin": "step to the center and take the bait gold",
                    "side_path": "take the slow side tunnel",
                    "jump": "sprint and jump the plates",
                },
            },
            "danger": {
                "type": "score",
                "instructions": "How deadly do these pressure plates look?",
                "criteria": ["mostly bluff", "painful if wrong", "could end the run"],
            },
            "trust_luck": {
                "type": "noul",
                "instructions": "Is grabbing the center coin worth the risk right now?",
            },
        }
    if kind == "merchant":
        return {
            "action": {
                "type": "choice",
                "instructions": "What deal should the adventurer take?",
                "criteria": {
                    "salve": "pay 3 gold for +4 hp if they can afford it",
                    "charm": "pay 5 gold for a relic if they can afford it",
                    "pass": "buy nothing and leave",
                },
            },
            "value": {
                "type": "score",
                "instructions": "How good is this merchant's pricing for a dungeon run?",
                "criteria": ["poor deals", "fair", "excellent"],
            },
            "spend_now": {
                "type": "noul",
                "instructions": "Should the adventurer spend gold here instead of saving it?",
            },
        }
    if kind == "shrine":
        return {
            "action": {
                "type": "choice",
                "instructions": "What should the adventurer do at the shrine?",
                "criteria": {
                    "kneel": "pray for healing, accepting curse risk",
                    "offer_gold": "leave 2 gold as offering for safer healing",
                    "ignore": "walk past",
                },
            },
            "danger": {
                "type": "score",
                "instructions": "How cursed does this shrine feel?",
                "criteria": ["benign", "uncertain", "clearly cursed"],
            },
            "need_heal": {
                "type": "noul",
                "instructions": "Does the adventurer need healing badly enough to risk the shrine?",
            },
        }
    if kind == "fork":
        return {
            "action": {
                "type": "choice",
                "instructions": "Which tunnel should the adventurer take?",
                "criteria": {
                    "left": "loud tunnel: likely fight, better loot",
                    "right": "quiet tunnel: safer, smaller loot",
                },
            },
            "greed": {
                "type": "score",
                "instructions": "How greedy should the adventurer be right now?",
                "criteria": ["play safe", "balanced", "push for loot"],
            },
            "feel_strong": {
                "type": "noul",
                "instructions": "Is the adventurer healthy enough for the dangerous left tunnel?",
            },
        }
    if kind == "treasure":
        return {
            "action": {
                "type": "choice",
                "instructions": "What should the adventurer do with the sealed chest?",
                "criteria": {
                    "open": "force it open for a possible relic",
                    "listen": "check for a trap first, smaller reward",
                    "leave": "leave it alone",
                },
            },
            "danger": {
                "type": "score",
                "instructions": "How trapped does this chest look?",
                "criteria": ["probably safe", "suspicious", "almost certainly trapped"],
            },
            "force_it": {
                "type": "noul",
                "instructions": "Should the adventurer force the chest open despite the risk?",
            },
        }
    # boss
    return {
        "action": {
            "type": "choice",
            "instructions": "How should the adventurer face the gate warden?",
            "criteria": {
                "charge": "full assault for glory and loot",
                "bribe": "offer gold to pass if they have enough",
                "smoke_slip": "use stealth and smoke to slip past",
            },
        },
        "danger": {
            "type": "score",
            "instructions": "How lethal is the gate warden?",
            "criteria": ["manageable", "deadly", "overwhelming"],
        },
        "all_in": {
            "type": "noul",
            "instructions": "Should the adventurer go all-in for a heroic finish?",
        },
    }


def state_for_player(player: dict, room: dict) -> dict:
    return {
        "game": "Ashen Gate",
        "adventurer": player["name"],
        "hp": player["hp"],
        "max_hp": player["max_hp"],
        "gold": player["gold"],
        "relics": player["relics"],
        "room_number": room["index"] + 1,
        "room_title": room["title"],
        "room_kind": room["kind"],
        "situation": room["blurb"],
        "recent_log": player["log"][-3:],
    }


def _choice(answers: dict, key: str, default: str) -> str:
    item = answers.get(key) or {}
    value = item.get("choice")
    return value if isinstance(value, str) else default


def _score(answers: dict, key: str, default: float = 1.0) -> float:
    item = answers.get(key) or {}
    value = item.get("score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _yes(answers: dict, key: str, default: bool = False) -> bool:
    item = answers.get(key) or {}
    value = item.get("noul")
    if value is None:
        return default
    try:
        return float(value) >= 0.5
    except (TypeError, ValueError):
        return default


def _clamp_hp(player: dict) -> None:
    player["hp"] = max(0, min(player["max_hp"], int(player["hp"])))
    if player["hp"] <= 0:
        player["alive"] = False
        player["finished"] = True


def _add_log(player: dict, line: str) -> None:
    player["log"].append(line)


def apply_answers(player: dict, room: dict, answers: dict, rng: random.Random) -> dict:
    """Resolve one room from model answers. Mutates player. Returns a turn summary."""
    if not player["alive"] or player["finished"]:
        return {"skipped": True, "lines": ["Already finished."]}

    kind = room["kind"]
    lines: list[str] = []
    action = _choice(answers, "action", "flee" if kind == "monster" else "pass")

    if kind == "monster":
        strength = room["meta"]["strength"]
        use_smoke = _yes(answers, "use_smoke")
        danger = _score(answers, "danger", strength - 1)
        mitigation = 1 if use_smoke else 0
        if action == "fight":
            damage = max(0, strength - mitigation + (1 if danger >= 1.5 else 0))
            player["hp"] -= damage
            gained = room["meta"]["reward"]
            player["gold"] += gained
            lines.append(f"Fought. Took {damage} damage, looted {gained} gold.")
        elif action == "sneak":
            if rng.random() < 0.55 + (0.2 if use_smoke else 0):
                gained = max(1, room["meta"]["reward"] // 2)
                player["gold"] += gained
                lines.append(f"Slipped past. Pocketed {gained} gold.")
            else:
                damage = max(1, strength - mitigation)
                player["hp"] -= damage
                lines.append(f"Spotted while sneaking. Took {damage} damage.")
        else:
            player["hp"] -= 1
            lines.append("Fled the long way. Lost 1 hp to exhaustion.")

    elif kind == "trap":
        if action == "grab_coin" or (_yes(answers, "trust_luck") and action != "side_path"):
            if action != "grab_coin":
                action = "grab_coin"
            if rng.random() < 0.45:
                player["gold"] += room["meta"]["bait_gold"]
                lines.append(f"Snatching the coin worked. +{room['meta']['bait_gold']} gold.")
            else:
                player["hp"] -= 3
                lines.append("Plate triggered. Spring dart for 3 damage.")
        elif action == "jump":
            if rng.random() < 0.5:
                player["gold"] += 2
                lines.append("Jump cleared it. Found 2 gold in a crack.")
            else:
                player["hp"] -= 2
                lines.append("Bad landing. 2 damage.")
        else:
            player["gold"] += room["meta"]["safe_gold"]
            lines.append(f"Took the side path. +{room['meta']['safe_gold']} gold.")

    elif kind == "merchant":
        spend = _yes(answers, "spend_now")
        if action == "salve" and spend and player["gold"] >= 3:
            player["gold"] -= 3
            player["hp"] += 4
            lines.append("Bought salve. -3 gold, +4 hp.")
        elif action == "charm" and spend and player["gold"] >= 5:
            player["gold"] -= 5
            player["relics"] += 1
            lines.append("Bought charm. -5 gold, +1 relic.")
        elif action in ("salve", "charm") and not (spend and player["gold"] >= (3 if action == "salve" else 5)):
            lines.append("Wanted a deal but could not (or would not) pay. Moved on.")
        else:
            lines.append("Passed the merchant.")

    elif kind == "shrine":
        need = _yes(answers, "need_heal")
        cursed_feel = _score(answers, "danger", 1.0)
        if action == "offer_gold" and player["gold"] >= 2:
            player["gold"] -= 2
            player["hp"] += 3
            lines.append("Offered 2 gold. Shrine healed +3 hp.")
        elif action == "kneel" or (need and action != "ignore"):
            if cursed_feel >= 1.5 and rng.random() < 0.5:
                player["hp"] -= 2
                lines.append("The shrine cursed you. -2 hp.")
            else:
                player["hp"] += 5
                lines.append("Prayer answered. +5 hp.")
        else:
            lines.append("Ignored the shrine.")

    elif kind == "fork":
        strong = _yes(answers, "feel_strong")
        greed = _score(answers, "greed", 1.0)
        take_left = action == "left" or (strong and greed >= 1.4 and action != "right")
        if take_left:
            if rng.random() < 0.6:
                player["gold"] += 5
                player["hp"] -= 2
                lines.append("Left tunnel fight won. +5 gold, -2 hp.")
            else:
                player["hp"] -= 3
                player["gold"] += 1
                lines.append("Left tunnel went badly. -3 hp, +1 gold.")
        else:
            player["gold"] += 2
            lines.append("Right tunnel was quiet. +2 gold.")

    elif kind == "treasure":
        if action == "open" or (_yes(answers, "force_it") and action != "leave"):
            if rng.random() < 0.5:
                player["relics"] += 1
                player["gold"] += 3
                lines.append("Chest opened. Relic secured, +3 gold.")
            else:
                player["hp"] -= 3
                lines.append("Chest trap. Blade cut for 3 damage.")
        elif action == "listen":
            player["gold"] += 2
            lines.append("Heard a click, disarmed carefully. +2 gold.")
        else:
            lines.append("Left the chest untouched.")

    elif kind == "boss":
        all_in = _yes(answers, "all_in")
        if action == "bribe" and player["gold"] >= 8:
            player["gold"] -= 8
            lines.append("Bribed the warden with 8 gold. The gate opens.")
        elif action == "smoke_slip":
            if rng.random() < (0.7 if not all_in else 0.55):
                player["gold"] += 4
                lines.append("Slipped past in smoke. +4 gold beyond the gate.")
            else:
                player["hp"] -= 4
                lines.append("Warden caught the slip. -4 hp, still escaped battered.")
        else:
            damage = 3 if all_in else 4
            player["hp"] -= damage
            player["gold"] += room["meta"]["reward"]
            player["relics"] += 1
            lines.append(f"Charged the warden. -{damage} hp, +{room['meta']['reward']} gold, +1 relic.")

    _clamp_hp(player)
    for line in lines:
        _add_log(player, line)

    if not player["alive"]:
        _add_log(player, "Fell in the Ashen Gate.")
    else:
        player["room"] = room["index"] + 1
        if player["room"] >= ROOM_COUNT:
            player["finished"] = True
            _add_log(player, "Cleared the Ashen Gate.")

    player["score"] = final_score(player)
    player["last_decision"] = {
        "action": action,
        "answers": answers,
        "room": room["title"],
    }
    return {"skipped": False, "lines": lines, "action": action}


def final_score(player: dict) -> int:
    # Survive further, keep hp, bank gold and relics.
    return (
        player["room"] * 10
        + player["gold"] * 2
        + player["relics"] * 25
        + (player["hp"] * 3 if player["alive"] else 0)
        + (40 if player["finished"] and player["alive"] else 0)
    )


def public_player(player: dict) -> dict:
    return {
        "name": player["name"],
        "hp": player["hp"],
        "max_hp": player["max_hp"],
        "gold": player["gold"],
        "relics": player["relics"],
        "room": player["room"],
        "alive": player["alive"],
        "finished": player["finished"],
        "score": player["score"],
        "log": list(player["log"]),
        "last_decision": player.get("last_decision"),
        "last_latency_ms": player.get("last_latency_ms"),
    }


def start_game(models: list[str], seed: int | None = None) -> dict:
    seed = int(seed if seed is not None else random.randint(1, 999999))
    rooms = _rooms_for_seed(seed)
    session_id = uuid.uuid4().hex[:10]
    players = {}
    for name in models:
        if name not in ("jev", "laya"):
            continue
        players[name] = _new_player("Jev" if name == "jev" else "Laya")

    if not players:
        raise ValueError("Pick at least one of jev or laya.")

    session = {
        "id": session_id,
        "seed": seed,
        "rooms": rooms,
        "players": players,
        "models": list(players.keys()),
    }
    _SESSIONS[session_id] = session
    return snapshot(session)


def get_session(session_id: str) -> dict | None:
    return _SESSIONS.get(session_id)


def snapshot(session: dict) -> dict:
    rooms = session["rooms"]
    players_out = {}
    pending = {}
    for name, player in session["players"].items():
        players_out[name] = public_player(player)
        if player["alive"] and not player["finished"]:
            room = rooms[player["room"]]
            pending[name] = {
                "room": {
                    "index": room["index"],
                    "kind": room["kind"],
                    "title": room["title"],
                    "blurb": room["blurb"],
                },
                "state": state_for_player(player, room),
                "questions": questions_for_room(room),
            }

    done = all(p["finished"] or not p["alive"] for p in session["players"].values())
    ranking = sorted(
        (
            {"model": name, "score": p["score"], "alive": p["alive"], "room": p["room"]}
            for name, p in session["players"].items()
        ),
        key=lambda row: row["score"],
        reverse=True,
    )
    return {
        "session_id": session["id"],
        "seed": session["seed"],
        "room_count": ROOM_COUNT,
        "done": done,
        "players": players_out,
        "pending": pending,
        "ranking": ranking,
        "rooms_preview": [
            {"index": r["index"], "kind": r["kind"], "title": r["title"]} for r in rooms
        ],
    }


def apply_model_turn(session: dict, model: str, answers: dict, latency_ms: float | None) -> dict:
    player = session["players"][model]
    if not player["alive"] or player["finished"]:
        return {"lines": ["No turn."], "action": None}

    room = session["rooms"][player["room"]]
    rng = random.Random(f"{session['seed']}-{model}-{room['index']}")
    result = apply_answers(player, room, answers or {}, rng)
    player["last_latency_ms"] = latency_ms
    return result


def clone_pending_state(session: dict, model: str) -> tuple[Any, dict] | None:
    pending = snapshot(session)["pending"].get(model)
    if not pending:
        return None
    return copy.deepcopy(pending["state"]), copy.deepcopy(pending["questions"])
