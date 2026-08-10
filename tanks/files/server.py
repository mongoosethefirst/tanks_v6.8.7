# -*- coding: utf-8 -*-
import json
import math
import random
import socket
import string
import threading
import time

from network import GAME_VERSION, TCP_PORT, DISCOVERY_PORT, TICK_RATE, STATE_RATE, send_json

class GameServer:
    def __init__(self, host="0.0.0.0", port=TCP_PORT, match_minutes=10, scrap_spawn_factor=1.0, ammo_spawn_factor=1.0, health_spawn_factor=1.0, max_players=8, starting_ammo=30, max_health=100, respawn_seconds=3, friendly_fire=False, free_for_all=False):
        self.host = host
        self.port = port
        self.match_minutes = max(1, min(120, int(match_minutes)))
        self.scrap_spawn_factor = max(0.1, min(5.0, float(scrap_spawn_factor)))
        self.ammo_spawn_factor = max(0.1, min(5.0, float(ammo_spawn_factor)))
        self.health_spawn_factor = max(0.1, min(5.0, float(health_spawn_factor)))
        self.max_players = max(2, min(16, int(max_players)))
        if self.max_players % 2:
            self.max_players -= 1
        self.max_team_players = self.max_players // 2
        self.starting_ammo = max(0, min(200, int(starting_ammo)))
        self.max_health = max(10, min(500, int(max_health)))
        self.respawn_seconds = max(1, min(15, int(respawn_seconds)))
        self.friendly_fire = bool(friendly_fire)
        self.free_for_all = bool(free_for_all)
        extra_pairs = (self.max_players - 2) // 2
        self.map_size = max(20, round(20 * math.sqrt(1 + 0.25 * extra_pairs)))
        self.match_seconds = self.match_minutes * 60
        self.match_started = False
        self.match_start_time = None
        self.countdown_end = None
        self.host_id = None
        self.join_code = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        self.players = {}
        self.clients = {}
        self.inputs = {}
        self.bullets = []
        self.impacts = []
        self.field = []
        self.ammo_positions = []
        self.scrap_positions = []
        self.health_positions = []
        self.chat = []
        self.next_player_id = 0
        self.next_bullet_id = 0
        self.running = False
        self.match_over = False
        self.winner = None
        self.rematch_seconds = 15
        self.rematch_start_time = None
        self.next_heal_times = {}
        self.respawn_times = {}
        self.lock = threading.RLock()
        self.server_socket = None
        self.next_scrap_spawn = time.monotonic() + random.uniform(5, 15)
        self.next_ammo_spawn = time.monotonic() + random.uniform(5, 15)
        self.next_health_spawn = time.monotonic() + 30
        self.create_field()

    def create_field(self):
        self.field = []
        self.ammo_positions = []
        self.scrap_positions = []
        self.health_positions = []
        self.field.append([["corner", 0]] + [["edge", 1] for _ in range(self.map_size)] + [["corner", 1]])

        for y in range(self.map_size):
            line = [["edge", 0]]

            for x in range(self.map_size):
                line.append(["grass" + str(random.randint(1, 4)), random.randint(0, 3)])

            line.append(["edge", 2])
            self.field.append(line)

        self.field.append([["corner", 3]] + [["edge", 3] for _ in range(self.map_size)] + [["corner", 2]])

    def add_chat(self, message):
        self.chat.append(message)
        self.chat = self.chat[-8:]

    def choose_team(self):
        if self.free_for_all:
            return -1
        counts = [sum(1 for player in self.players.values() if player["team"] == team) for team in (0, 1)]

        if counts[0] >= self.max_team_players and counts[1] >= self.max_team_players:
            return None
        if counts[0] >= self.max_team_players:
            return 1
        if counts[1] >= self.max_team_players:
            return 0
        return 0 if counts[0] <= counts[1] else 1

    def spawn_position(self, team, slot=0, ignore_player_id=None):
        minimum_distance = 1.8

        for _ in range(100):
            if self.free_for_all:
                side = random.randint(0, 3)
                if side == 0:
                    x, y, rot = random.uniform(0.8, self.map_size - 1.8), 0.8, 180
                elif side == 1:
                    x, y, rot = random.uniform(0.8, self.map_size - 1.8), self.map_size - 1.8, 0
                elif side == 2:
                    x, y, rot = 0.8, random.uniform(0.8, self.map_size - 1.8), 270
                else:
                    x, y, rot = self.map_size - 1.8, random.uniform(0.8, self.map_size - 1.8), 90
            else:
                y = 0.8 if team == 0 else self.map_size - 1.8
                rot = 180 if team == 0 else 0
                x = random.uniform(0.8, max(0.8, self.map_size - 1.8))

            if not self.tank_blocked(x, y, rot):
                too_close = any(
                    other["alive"] and other_id != ignore_player_id and
                    math.hypot(other["x"] - x, other["y"] - y) < minimum_distance
                    for other_id, other in self.players.items()
                )
                if not too_close:
                    return x, y, rot

        if self.free_for_all:
            side = slot % 4
            fraction = ((slot // 4) + 1) / (max(1, math.ceil(self.max_players / 4)) + 1)
            along = 0.8 + fraction * max(1.0, self.map_size - 2.6)
            if side == 0:
                return along, 0.8, 180
            if side == 1:
                return along, self.map_size - 1.8, 0
            if side == 2:
                return 0.8, along, 270
            return self.map_size - 1.8, along, 90

        y = 0.8 if team == 0 else self.map_size - 1.8
        rot = 180 if team == 0 else 0
        slots = max(1, self.max_team_players)
        x = 0.8 + ((slot + 1) / (slots + 1)) * max(1.0, self.map_size - 2.6)
        return x, y, rot

    def spawn_for(self, player_id, team):
        if self.free_for_all:
            slot = sum(1 for player in self.players.values() if player["id"] < player_id)
        else:
            slot = sum(1 for player in self.players.values() if player["team"] == team and player["id"] < player_id)
        return self.spawn_position(team, slot, player_id)

    def add_player(self, name, color):
        with self.lock:
            if len(self.players) >= self.max_players or self.match_over or self.match_started or self.countdown_end is not None:
                return None

            team = self.choose_team()

            if team is None:
                return None

            player_id = self.next_player_id
            self.next_player_id += 1
            x, y, rot = self.spawn_for(player_id, team)
            self.players[player_id] = {
                "id": player_id,
                "name": (name.strip() or "PLAYER")[:20],
                "color": color,
                "team": team,
                "x": x,
                "y": y,
                "tread_rot": rot,
                "head_rot": rot,
                "health": self.max_health,
                "ammo": self.starting_ammo,
                "scrap": 0,
                "alive": True,
                "tread_frame": 0.0,
                "kills": 0,
                "deaths": 0,
                "ping": 0,
                "invulnerable_until": 0.0,
                "hotbar": [],
                "shield_until": 0.0,
                "rapid_until": 0.0,
                "engine_until": [],
                "explosive_rounds": 0,
                "last_shot_time": 0.0
            }
            self.inputs[player_id] = {"left": False, "right": False, "forward": False, "backward": False, "aim": rot}
            self.next_heal_times[player_id] = time.monotonic() + 5
            if self.host_id is None:
                self.host_id = player_id
            self.add_chat(self.players[player_id]["name"] + " joined!")
            return player_id

    def remove_player(self, player_id):
        with self.lock:
            player = self.players.pop(player_id, None)
            self.inputs.pop(player_id, None)
            self.next_heal_times.pop(player_id, None)
            self.respawn_times.pop(player_id, None)
            client = self.clients.pop(player_id, None)

            if client:
                try:
                    client.close()
                except OSError:
                    pass

            if player and not self.match_over:
                self.add_chat(player["name"] + " disconnected.")
            if player_id == self.host_id:
                self.host_id = min(self.players.keys()) if self.players else None

    def can_start_match(self):
        if self.match_started or self.countdown_end is not None or len(self.players) < 2:
            return False
        if self.free_for_all:
            return True
        team_counts = [sum(1 for player in self.players.values() if player["team"] == team) for team in (0, 1)]
        return team_counts[0] > 0 and team_counts[1] > 0

    def request_start_match(self, player_id):
        if player_id != self.host_id or not self.can_start_match():
            return
        self.countdown_end = time.monotonic() + 3.0
        self.add_chat("Match starting!")

    def update_countdown(self, now):
        if self.countdown_end is None or self.match_started:
            return
        if now < self.countdown_end:
            return
        self.match_started = True
        self.match_start_time = now
        self.countdown_end = None
        self.next_scrap_spawn = now + random.uniform(5, 15)
        self.next_ammo_spawn = now + random.uniform(5, 15)
        self.next_health_spawn = now + 30
        self.add_chat("GO!")

    def blocked_tile(self, x, y):
        item = math.floor(x + 1.5)
        row = math.floor(y + 1.5)

        if row < 0 or row >= len(self.field) or item < 0 or item >= len(self.field[row]):
            return True

        return self.field[row][item][0] in ("edge", "corner")

    def tank_blocked(self, x, y, rot):
        half = 0.4
        radians = math.radians(-rot)
        cosine = math.cos(radians)
        sine = math.sin(radians)
        points = [(-half, -half), (half, -half), (-half, half), (half, half), (0, -half), (0, half), (-half, 0), (half, 0)]

        for offset_x, offset_y in points:
            rotated_x = offset_x * cosine - offset_y * sine
            rotated_y = offset_x * sine + offset_y * cosine

            if self.blocked_tile(x + rotated_x, y + rotated_y):
                return True

        return False

    def turn_toward(self, current, target, amount):
        difference = (target - current + 180) % 360 - 180
        return (current + max(-amount, min(amount, difference))) % 360

    def object_at(self, x, y, include_players=True):
        for position in self.ammo_positions:
            if math.hypot(position[0] - x, position[1] - y) < 0.7:
                return True

        for position in self.scrap_positions:
            if math.hypot(position[0] - x, position[1] - y) < 0.7:
                return True

        for position in self.health_positions:
            if math.hypot(position[0] - x, position[1] - y) < 0.7:
                return True

        if include_players:
            for player in self.players.values():
                if player["alive"] and math.hypot(player["x"] - x, player["y"] - y) < 0.9:
                    return True

        return False

    def random_open_position(self):
        available = []

        for y in range(self.map_size):
            for x in range(self.map_size):
                if not self.object_at(x, y):
                    available.append((x, y))

        return random.choice(available) if available else None

    def open_drop_position(self, center_x, center_y, starting_radius=2):
        center_x = round(center_x)
        center_y = round(center_y)

        for radius in range(starting_radius, self.map_size + 1):
            available = []

            for y in range(max(0, center_y - radius), min(self.map_size, center_y + radius + 1)):
                for x in range(max(0, center_x - radius), min(self.map_size, center_x + radius + 1)):
                    if math.hypot(x - center_x, y - center_y) <= radius and not self.object_at(x, y):
                        available.append((x, y))

            if available:
                return random.choice(available)

        return None

    def object_caps(self):
        area_scale = (self.map_size * self.map_size) / 400.0
        return {
            "scrap": max(10, round(40 * area_scale)),
            "ammo": max(8, round(30 * area_scale)),
            "health": max(4, round(12 * area_scale))
        }

    def spawn_scrap(self):
        if len(self.scrap_positions) >= self.object_caps()["scrap"]:
            return
        position = self.random_open_position()
        if position:
            self.scrap_positions.append([position[0], position[1]])

    def spawn_ammo(self):
        if len(self.ammo_positions) >= self.object_caps()["ammo"]:
            return
        position = self.random_open_position()
        if position:
            self.ammo_positions.append([position[0], position[1], 10])

    def spawn_health(self):
        if len(self.health_positions) >= self.object_caps()["health"]:
            return
        position = self.random_open_position()
        if position:
            self.health_positions.append([position[0], position[1]])

    def drop_scrap(self, player):
        amount = player["scrap"]
        player["scrap"] = 0

        available_slots = max(0, self.object_caps()["scrap"] - len(self.scrap_positions))
        for _ in range(min(amount, available_slots)):
            position = self.open_drop_position(player["x"], player["y"], 2)

            if position:
                self.scrap_positions.append([position[0], position[1]])

    def buy_item(self, player_id, item):
        player = self.players.get(player_id)
        prices = {"ammo_pack": 5, "repair": 8, "shield": 10, "rapid_fire": 30, "explosive_rounds": 20, "engine_upgrade": 10}
        if not self.match_started or self.match_over or not player or not player["alive"] or item not in prices or len(player.get("hotbar", [])) >= 10:
            return
        price = prices[item]
        if player["scrap"] < price:
            return
        player["scrap"] -= price
        player.setdefault("hotbar", []).append(item)

    def use_hotbar(self, player_id, slot):
        player = self.players.get(player_id)
        if not self.match_started or self.match_over or not player or not player["alive"] or slot < 0 or slot >= len(player.get("hotbar", [])):
            return
        item = player["hotbar"][slot]
        now = time.monotonic()
        if item == "repair" and player["health"] >= self.max_health:
            return
        player["hotbar"].pop(slot)
        if item == "ammo_pack":
            player["ammo"] += 10
        elif item == "repair":
            player["health"] = min(self.max_health, player["health"] + 30)
        elif item == "shield":
            player["shield_until"] = max(now, player.get("shield_until", 0.0)) + 10.0
        elif item == "rapid_fire":
            player["rapid_until"] = max(now, player.get("rapid_until", 0.0)) + 10.0
        elif item == "explosive_rounds":
            player["ammo"] += 10
            player["explosive_rounds"] = player.get("explosive_rounds", 0) + 10
        elif item == "engine_upgrade":
            player.setdefault("engine_until", []).append(now + 10.0)

    def shoot(self, player_id):
        player = self.players.get(player_id)
        now = time.monotonic()
        if self.match_over or not self.match_started or not player or not player["alive"] or player["ammo"] <= 0:
            return
        cooldown = 0.5 / (3.0 if now < player.get("rapid_until", 0.0) else 1.0)
        if now - player.get("last_shot_time", 0.0) < cooldown:
            return
        player["last_shot_time"] = now
        explosive = player.get("explosive_rounds", 0) > 0
        if explosive:
            player["explosive_rounds"] -= 1
        direction = player["head_rot"]
        self.bullets.append({
            "id": self.next_bullet_id, "owner": player_id, "team": player["team"],
            "x": player["x"] - math.sin(math.radians(direction)) * 0.65,
            "y": player["y"] - math.cos(math.radians(direction)) * 0.65,
            "direction": direction, "distance": 0.0, "explosive": explosive
        })
        self.next_bullet_id += 1
        player["ammo"] -= 1

    def respawn(self, player_id):
        player = self.players.get(player_id)
        if self.match_over or not player or player["alive"]:
            return
        x, y, rot = self.spawn_for(player_id, player["team"])
        player.update({
            "x": x, "y": y, "tread_rot": rot, "head_rot": rot,
            "health": self.max_health, "ammo": 10, "scrap": 0, "alive": True,
            "invulnerable_until": time.monotonic() + 1.5
        })
        self.respawn_times.pop(player_id, None)
        self.next_heal_times[player_id] = time.monotonic() + 5

    def update_respawns(self, now):
        for player_id, when in list(self.respawn_times.items()):
            if now >= when:
                self.respawn(player_id)

    def tank_hits_player(self, player_id, x, y):
        for other_id, other in self.players.items():
            if other_id != player_id and other["alive"] and math.hypot(other["x"] - x, other["y"] - y) < 0.82:
                return True
        return False

    def update_healing(self, now):
        for player_id, player in self.players.items():
            if not player["alive"]:
                continue

            next_heal = self.next_heal_times.get(player_id, now + 5)

            if now >= next_heal:
                if player["health"] < self.max_health:
                    player["health"] = min(self.max_health, player["health"] + 5)
                self.next_heal_times[player_id] = now + 5

    def update_players(self, dt):
        for player_id, player in self.players.items():
            if not player["alive"]:
                continue

            controls = self.inputs.get(player_id, {})
            new_rot = player["tread_rot"]

            if controls.get("left"):
                new_rot += 120 * dt
            if controls.get("right"):
                new_rot -= 120 * dt

            new_rot %= 360

            if not self.tank_blocked(player["x"], player["y"], new_rot):
                player["tread_rot"] = new_rot

            player["head_rot"] = self.turn_toward(player["head_rot"], controls.get("aim", player["head_rot"]), 240 * dt)
            direction = int(bool(controls.get("forward"))) - int(bool(controls.get("backward")))

            if direction:
                damage_fraction = max(0.0, min(1.0, (self.max_health - player["health"]) / max(1, self.max_health * 0.9)))
                speed_multiplier = 1.0 + 0.30 * damage_fraction
                now = time.monotonic()
                player["engine_until"] = [t for t in player.get("engine_until", []) if t > now]
                engine_multiplier = 1.5 ** len(player["engine_until"])
                move_speed = 1.2 * speed_multiplier * engine_multiplier
                new_x = player["x"] - math.sin(math.radians(player["tread_rot"])) * move_speed * dt * direction
                new_y = player["y"] - math.cos(math.radians(player["tread_rot"])) * move_speed * dt * direction

                if not self.tank_blocked(new_x, new_y, player["tread_rot"]) and not self.tank_hits_player(player_id, new_x, new_y):
                    player["x"] = new_x
                    player["y"] = new_y
                    player["tread_frame"] -= 18 * speed_multiplier * engine_multiplier * dt * direction

            for ammo in self.ammo_positions[:]:
                if math.hypot(ammo[0] - player["x"], ammo[1] - player["y"]) < 0.8:
                    player["ammo"] += ammo[2]
                    self.ammo_positions.remove(ammo)

            for scrap in self.scrap_positions[:]:
                if math.hypot(scrap[0] - player["x"], scrap[1] - player["y"]) < 0.75:
                    player["scrap"] += 1
                    self.scrap_positions.remove(scrap)

            if player["health"] <= self.max_health / 2:
                for health in self.health_positions[:]:
                    if math.hypot(health[0] - player["x"], health[1] - player["y"]) < 0.75:
                        player["health"] = min(self.max_health, player["health"] + max(1, self.max_health // 2))
                        self.health_positions.remove(health)
                        break

    def add_bullet_impact(self, bullet):
        self.impacts.append({
            "id": bullet["id"],
            "x": bullet["x"],
            "y": bullet["y"],
            "direction": bullet["direction"],
            "ttl": 0.18
        })

    def update_impacts(self, dt):
        for impact in self.impacts:
            impact["ttl"] -= dt
        self.impacts = [impact for impact in self.impacts if impact["ttl"] > 0]

    def damage_player(self, player, amount, shooter):
        if time.monotonic() < player.get("invulnerable_until", 0):
            return
        if time.monotonic() < player.get("shield_until", 0):
            amount *= 0.5
        player["health"] = max(0, player["health"] - max(1, round(amount)))
        if player["health"] == 0 and player["alive"]:
            player["alive"] = False
            player["deaths"] += 1
            self.drop_scrap(player)
            self.respawn_times[player["id"]] = time.monotonic() + self.respawn_seconds
            if shooter:
                shooter["kills"] += 1
                self.add_chat(random.choice([shooter["name"] + " shot " + player["name"] + "!", player["name"] + " was exploded by " + shooter["name"] + "!", player["name"] + " died.", shooter["name"] + " killed " + player["name"]]))
            else:
                self.add_chat(player["name"] + " died.")

    def update_bullets(self, dt):
        remaining = []
        for bullet in self.bullets:
            bullet["x"] -= math.sin(math.radians(bullet["direction"])) * 6 * dt
            bullet["y"] -= math.cos(math.radians(bullet["direction"])) * 6 * dt
            bullet["distance"] += 6 * dt
            stopped = bullet["distance"] >= 6 or self.blocked_tile(bullet["x"], bullet["y"])
            hit = None
            if not stopped:
                for player in self.players.values():
                    enemy_ok = self.free_for_all or self.friendly_fire or player["team"] != bullet["team"]
                    if player["alive"] and player["id"] != bullet["owner"] and enemy_ok and math.hypot(player["x"] - bullet["x"], player["y"] - bullet["y"]) < 0.48:
                        hit = player
                        break
            if stopped or hit:
                self.add_bullet_impact(bullet)
                shooter = self.players.get(bullet["owner"])
                if bullet.get("explosive"):
                    for player in self.players.values():
                        enemy_ok = self.free_for_all or self.friendly_fire or player["team"] != bullet["team"]
                        if player["alive"] and player["id"] != bullet["owner"] and enemy_ok and math.hypot(player["x"] - bullet["x"], player["y"] - bullet["y"]) <= 1.25:
                            self.damage_player(player, 10, shooter)
                elif hit:
                    self.damage_player(hit, 10, shooter)
                continue
            remaining.append(bullet)
        self.bullets = remaining

    def scrap_player_multiplier(self):
        return max(1.0, len(self.players) / 2)

    def ammo_player_multiplier(self):
        return self.scrap_player_multiplier() + 0.5

    def update_spawns(self, now):
        if not self.match_started or self.match_over:
            return

        scrap_multiplier = self.scrap_player_multiplier()
        ammo_multiplier = self.ammo_player_multiplier()

        if now >= self.next_scrap_spawn:
            if random.random() < 0.7:
                self.spawn_scrap()
            original_interval = max(3.0, random.uniform(5, 15) / scrap_multiplier)
            self.next_scrap_spawn = now + original_interval / self.scrap_spawn_factor

        if now >= self.next_ammo_spawn:
            if random.random() < 0.7:
                self.spawn_ammo()
            original_interval = max(3.0, random.uniform(5, 15) / ammo_multiplier)
            self.next_ammo_spawn = now + original_interval / self.ammo_spawn_factor

        if now >= self.next_health_spawn:
            self.spawn_health()
            original_interval = max(8.0, 30 / scrap_multiplier)
            self.next_health_spawn = now + original_interval / self.health_spawn_factor

    def time_remaining(self):
        if not self.match_started or self.match_start_time is None:
            return self.match_seconds

        return max(0, self.match_seconds - (time.monotonic() - self.match_start_time))

    def team_scrap_totals(self):
        totals = [0, 0]
        if self.free_for_all:
            return totals
        for player in self.players.values():
            totals[player["team"]] += player["scrap"]
        return totals

    def determine_winner(self):
        rankings = self.get_rankings()
        if not rankings:
            return -1

        if self.free_for_all:
            best = rankings[0]
            same_rank = [row for row in rankings if (row["difference"], row["kills"], -row["deaths"], row.get("scrap", 0)) == (best["difference"], best["kills"], -best["deaths"], best.get("scrap", 0))]
            return best["id"] if len(same_rank) == 1 else -1

        totals = self.team_scrap_totals()
        if totals[0] > totals[1]:
            return 0
        if totals[1] > totals[0]:
            return 1

        best = rankings[0]
        same_rank = [row for row in rankings if (row["difference"], row["kills"], -row["deaths"]) == (best["difference"], best["kills"], -best["deaths"])]
        teams = {row["team"] for row in same_rank}
        return best["team"] if len(teams) == 1 else -1

    def check_match_end(self):
        if self.match_over or not self.match_started:
            return

        if self.time_remaining() > 0:
            return

        self.match_over = True
        self.winner = self.determine_winner()
        self.rematch_start_time = time.monotonic()

        if self.winner == -1:
            self.add_chat("Match ended in a draw!")
        elif self.free_for_all:
            winner_player = self.players.get(self.winner)
            self.add_chat((winner_player["name"] if winner_player else "A player") + " wins!")
        else:
            self.add_chat("Team " + str(self.winner + 1) + " wins!")


    def rematch_time_remaining(self):
        if not self.match_over or self.rematch_start_time is None:
            return 0
        return max(0, self.rematch_seconds - (time.monotonic() - self.rematch_start_time))

    def start_new_match(self):
        player_ids = list(self.players.keys())
        random.shuffle(player_ids)
        first_team = random.randint(0, 1)
        team_slots = [0, 0]

        self.create_field()
        self.bullets = []
        self.impacts = []
        self.match_over = False
        self.winner = None
        self.match_started = False
        self.match_start_time = None
        self.countdown_end = None
        self.host_id = None
        self.rematch_start_time = None
        self.next_bullet_id = 0
        self.chat = []
        self.respawn_times = {}

        for index, player_id in enumerate(player_ids):
            player = self.players[player_id]
            if self.free_for_all:
                team = -1
                slot = index
            else:
                team = (first_team + index) % 2
                slot = team_slots[team]
                team_slots[team] += 1
            x, y, rot = self.spawn_position(team, slot, player_id)
            player.update({
                "team": team,
                "x": x,
                "y": y,
                "tread_rot": rot,
                "head_rot": rot,
                "health": self.max_health,
                "ammo": self.starting_ammo,
                "scrap": 0,
                "alive": True,
                "tread_frame": 0.0,
                "kills": 0,
                "deaths": 0,
                "ping": player.get("ping", 0),
                "invulnerable_until": 0.0,
                "hotbar": [],
                "shield_until": 0.0,
                "rapid_until": 0.0,
                "engine_until": [],
                "explosive_rounds": 0,
                "last_shot_time": 0.0
            })
            self.inputs[player_id] = {"left": False, "right": False, "forward": False, "backward": False, "aim": rot}
            self.next_heal_times[player_id] = time.monotonic() + 5

        self.add_chat(("Free-for-all ready!" if self.free_for_all else "Teams randomized!") + " Host can start when ready.")

    def get_rankings(self):
        return sorted([
            {
                "id": player["id"],
                "name": player["name"],
                "team": player["team"],
                "kills": player["kills"],
                "deaths": player["deaths"],
                "difference": player["kills"] - player["deaths"],
                "scrap": player["scrap"]
            }
            for player in self.players.values()
        ], key=lambda row: (row["difference"], row["kills"], -row["deaths"], -row["id"]), reverse=True)

    def state_for(self, player_id):
        player = self.players.get(player_id)

        if not player:
            return {}

        scrap_totals = self.team_scrap_totals()
        now = time.monotonic()
        public_players = []

        for item in self.players.values():
            shown = dict(item)
            shown["respawn_remaining"] = max(0.0, self.respawn_times.get(item["id"], now) - now) if not item["alive"] else 0.0
            shown["spawn_protected"] = item["alive"] and now < item.get("invulnerable_until", 0)
            shown["shield_remaining"] = max(0.0, item.get("shield_until", 0.0) - now)
            shown["rapid_remaining"] = max(0.0, item.get("rapid_until", 0.0) - now)
            shown["engine_stacks"] = sum(1 for t in item.get("engine_until", []) if t > now)
            shown.pop("invulnerable_until", None)
            shown.pop("shield_until", None)
            shown.pop("rapid_until", None)
            shown.pop("engine_until", None)
            shown.pop("last_shot_time", None)
            public_players.append(shown)

        return {
            "type": "state",
            "you": player_id,
            "join_code": self.join_code,
            "field": self.field,
            "players": public_players,
            "bullets": self.bullets,
            "impacts": self.impacts,
            "ammo_positions": self.ammo_positions,
            "scrap_positions": self.scrap_positions,
            "health_positions": self.health_positions,
            "chat": self.chat,
            "team_scrap": player["scrap"] if self.free_for_all else scrap_totals[player["team"]],
            "team_scrap_totals": scrap_totals,
            "match_started": self.match_started,
            "host_id": self.host_id,
            "countdown_remaining": max(0.0, self.countdown_end - time.monotonic()) if self.countdown_end is not None else 0.0,
            "time_remaining": self.time_remaining(),
            "match_minutes": self.match_minutes,
            "max_players": self.max_players,
            "map_size": self.map_size,
            "spawn_factors": {"scrap": self.scrap_spawn_factor, "ammo": self.ammo_spawn_factor, "health": self.health_spawn_factor},
            "settings": {"starting_ammo": self.starting_ammo, "max_health": self.max_health, "respawn_seconds": self.respawn_seconds, "friendly_fire": self.friendly_fire, "free_for_all": self.free_for_all},
            "free_for_all": self.free_for_all,
            "object_caps": self.object_caps(),
            "match_over": self.match_over,
            "winner": self.winner,
            "rematch_time_remaining": self.rematch_time_remaining(),
            "version": GAME_VERSION,
            "rankings": self.get_rankings()
        }

    def broadcast_states(self):
        dead = []

        with self.lock:
            clients = list(self.clients.items())

        for player_id, client in clients:
            try:
                send_json(client, self.state_for(player_id))
            except OSError:
                dead.append(player_id)

        for player_id in dead:
            self.remove_player(player_id)

    def game_loop(self):
        last_time = time.perf_counter()
        state_timer = 0.0

        while self.running:
            now = time.perf_counter()
            monotonic_now = time.monotonic()
            dt = min(now - last_time, 0.05)
            last_time = now

            with self.lock:
                self.update_countdown(monotonic_now)

                if not self.match_over:
                    self.update_respawns(monotonic_now)
                    if self.match_started:
                        self.update_players(dt)
                    self.update_healing(monotonic_now)
                    self.update_bullets(dt)
                    self.update_impacts(dt)
                    self.update_spawns(monotonic_now)
                    self.check_match_end()
                elif self.rematch_time_remaining() <= 0:
                    self.start_new_match()

            state_timer += dt

            if state_timer >= 1 / STATE_RATE:
                self.broadcast_states()
                state_timer = 0.0

            wait = 1 / TICK_RATE - (time.perf_counter() - now)

            if wait > 0:
                time.sleep(wait)

    def discovery_loop(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(0.5)

            while self.running:
                try:
                    data, address = sock.recvfrom(4096)

                    if data.decode("utf-8", errors="ignore").strip() == "DISCOVER " + self.join_code:
                        sock.sendto(json.dumps({"join_code": self.join_code, "port": self.port}).encode("utf-8"), address)
                except socket.timeout:
                    pass
                except OSError:
                    if self.running:
                        pass
                    break

    def handle_client(self, client, address):
        player_id = None
        buffer = ""

        try:
            client.settimeout(10)

            while "\n" not in buffer:
                data = client.recv(65536)

                if not data:
                    return

                buffer += data.decode("utf-8")

            line, buffer = buffer.split("\n", 1)
            hello = json.loads(line)

            if hello.get("type") != "join":
                send_json(client, {"type": "error", "message": "Invalid connection request"})
                return

            if hello.get("join_code", "").strip().upper() != self.join_code:
                send_json(client, {"type": "error", "message": "INVALID JOIN CODE"})
                return

            client_version = str(hello.get("version", ""))

            if client_version != GAME_VERSION:
                shown_version = client_version or "UNKNOWN"
                send_json(client, {"type": "error", "message": "VERSION MISMATCH - SERVER " + GAME_VERSION + " / YOU " + shown_version})
                return

            player_id = self.add_player(hello.get("name", "PLAYER"), hello.get("color", "red"))

            if player_id is None:
                send_json(client, {"type": "error", "message": "Game is full or already ended"})
                return

            with self.lock:
                self.clients[player_id] = client

            client.settimeout(None)
            send_json(client, {"type": "welcome", "player_id": player_id, "join_code": self.join_code, "version": GAME_VERSION})

            while self.running:
                data = client.recv(65536)

                if not data:
                    break

                buffer += data.decode("utf-8")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)

                    if not line.strip():
                        continue

                    message = json.loads(line)

                    with self.lock:
                        if message.get("type") == "input" and player_id in self.inputs:
                            self.inputs[player_id] = {
                                "left": bool(message.get("left")),
                                "right": bool(message.get("right")),
                                "forward": bool(message.get("forward")),
                                "backward": bool(message.get("backward")),
                                "aim": float(message.get("aim", 0)) % 360
                            }
                        elif message.get("type") == "shoot":
                            self.shoot(player_id)
                        elif message.get("type") == "start_match":
                            self.request_start_match(player_id)
                        elif message.get("type") == "buy_item":
                            self.buy_item(player_id, str(message.get("item", "")))
                        elif message.get("type") == "use_hotbar":
                            self.use_hotbar(player_id, int(message.get("slot", -1)))
                        elif message.get("type") == "ping":
                            send_json(client, {"type": "pong", "sent": message.get("sent", 0)})
                        elif message.get("type") == "ping_report":
                            if player_id in self.players:
                                self.players[player_id]["ping"] = max(0, min(9999, int(message.get("ms", 0))))
        except (OSError, ConnectionError, json.JSONDecodeError, ValueError):
            pass
        finally:
            if player_id is not None:
                self.remove_player(player_id)
            else:
                try:
                    client.close()
                except OSError:
                    pass

    def accept_loop(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(self.max_players)
        self.server_socket.settimeout(0.5)

        while self.running:
            try:
                client, address = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client, address), daemon=True).start()
            except socket.timeout:
                pass
            except OSError:
                break

    def start(self):
        if self.running:
            return

        self.running = True
        threading.Thread(target=self.accept_loop, daemon=True).start()
        threading.Thread(target=self.discovery_loop, daemon=True).start()
        threading.Thread(target=self.game_loop, daemon=True).start()

    def stop(self):
        self.running = False

        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass

        with self.lock:
            for client in list(self.clients.values()):
                try:
                    client.close()
                except OSError:
                    pass
            self.clients.clear()