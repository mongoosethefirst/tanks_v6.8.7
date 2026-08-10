# -*- coding: utf-8 -*-
import json, math, socket, threading, time
import pygame
from network import GAME_VERSION, send_json
from paths import image_path, font_path


class GameClient:
    def __init__(self, host, port, join_code, name, color):
        self.host, self.port, self.join_code, self.name, self.color = host, port, join_code, name, color
        self.sock = None
        self.running = False
        self.player_id = None
        self.state = {}
        self.lock = threading.Lock()
        self.error = ""
        self.last_shot = 0
        self.last_ping_sent = 0
        self.ping_ms = 0

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect((self.host, self.port))
        self.sock.settimeout(None)
        send_json(self.sock, {"type": "join", "join_code": self.join_code, "name": self.name, "color": self.color, "version": GAME_VERSION})
        self.running = True
        threading.Thread(target=self.receive_loop, daemon=True).start()
        end = time.time() + 5

        while time.time() < end and self.player_id is None and not self.error:
            time.sleep(0.01)

        if self.error:
            raise ConnectionError(self.error)
        if self.player_id is None:
            raise TimeoutError("Server did not respond")

    def receive_loop(self):
        buffer = ""

        try:
            while self.running:
                data = self.sock.recv(65536)

                if not data:
                    raise ConnectionError

                buffer += data.decode()

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)

                    if not line.strip():
                        continue

                    message = json.loads(line)

                    if message.get("type") == "welcome":
                        self.player_id = message["player_id"]
                    elif message.get("type") == "state":
                        with self.lock:
                            self.state = message
                    elif message.get("type") == "pong":
                        sent = float(message.get("sent", 0))
                        self.ping_ms = max(0, round((time.time() - sent) * 1000))
                        try:
                            send_json(self.sock, {"type": "ping_report", "ms": self.ping_ms})
                        except OSError:
                            pass
                    elif message.get("type") == "error":
                        self.error = message.get("message", "Connection error")
                        self.running = False
        except Exception:
            if self.running:
                self.error = "Connection lost"
            self.running = False

    def load(self, name, size):
        return pygame.transform.scale(pygame.image.load(image_path(name)).convert_alpha(), size)

    def blit_body(self, screen, image, position, angle):
        rotated = pygame.transform.rotate(image, angle)
        offset = (pygame.Vector2(image.get_rect().center) - (53, 80)).rotate(-angle)
        screen.blit(rotated, rotated.get_rect(center=pygame.Vector2(position) + offset))

    def txt(self, screen, font, value, position, color=(240, 240, 240), anchor="topleft"):
        surface = font.render(str(value), True, color)
        rect = surface.get_rect()
        setattr(rect, anchor, position)
        screen.blit(surface, rect)
        return rect

    def transparent_box(self, screen, rect, alpha=128):
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        surface.fill((20, 20, 20, alpha))
        screen.blit(surface, rect.topleft)
        pygame.draw.rect(screen, (220, 220, 220), rect, 2)

    def run(self):
        pygame.init()
        screen = pygame.display.set_mode((0, 0))
        width, height = screen.get_size()
        clock = pygame.time.Clock()
        font = pygame.font.Font(font_path(), 16)
        small = pygame.font.Font(font_path(), 11)
        title = pygame.font.Font(font_path(), 40)
        timer_font = pygame.font.Font(font_path(), 34)
        images = {"tread" + str(i): self.load("tread" + str(i) + ".png", (80, 80)) for i in range(1, 4)}

        for color in ["red", "orange", "yellow", "green", "blue", "purple", "pink"]:
            images[color] = self.load(color + "body.png", (106, 160))

        for i in range(1, 5):
            images["grass" + str(i)] = self.load("grass" + str(i) + ".png", (100, 100))

        images["edge"] = self.load("edge.png", (100, 100))
        images["corner"] = self.load("corner.png", (100, 100))
        images["bullet"] = self.load("bullet.png", (10, 16))
        images["bullet_break"] = self.load("bullet_break.png", (10, 16))
        images["ammo"] = self.load("ammo_box.png", (60, 30))
        images["scrap"] = self.load("scrap.png", (34, 34))
        images["health"] = self.load("health_pot.png", (34, 34))
        images["shop_icon"] = self.load("shop_icon.png", (32, 32))
        images["repair"] = self.load("repair.png", (28, 28))
        images["shield"] = self.load("shield.png", (28, 28))
        images["rapid_fire"] = self.load("rapid_fire.png", (28, 28))
        images["explosive_rounds"] = self.load("explosive_rounds.png", (28, 28))
        images["engine_upgrade"] = self.load("engine_upgrade.png", (28, 28))
        images["ammo_pack"] = self.load("ammo_box.png", (42, 21))
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        field_surface = None
        field_text = None
        input_timer = 0
        shop_open = False
        purchase_flash = 0.0
        number_keys = [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9, pygame.K_0]
        shop_items = [
            ("ammo_pack", "AMMO PACK", "+10 AMMO", 5),
            ("repair", "REPAIR", "+30 HEALTH", 8),
            ("shield", "SHIELD", "50% DAMAGE / 10s", 10),
            ("rapid_fire", "RAPID FIRE", "3x FIRE RATE / 10s", 30),
            ("explosive_rounds", "EXPLOSIVE ROUNDS", "+10 AMMO / 10 SPLASH SHOTS", 20),
            ("engine_upgrade", "ENGINE UPGRADE", "1.5x SPEED / 10s / STACKS", 10)
        ]

        while self.running:
            dt = clock.tick(60) / 1000
            purchase_flash = max(0.0, purchase_flash - dt)
            clicked = False
            mouse = pygame.mouse.get_pos()

            if time.time() - self.last_ping_sent >= 1.0:
                try:
                    send_json(self.sock, {"type": "ping", "sent": time.time()})
                    self.last_ping_sent = time.time()
                except OSError:
                    self.error = "Connection lost"
                    self.running = False
                    break

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    clicked = True
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_b:
                        shop_open = not shop_open
                    elif event.key in number_keys:
                        send_json(self.sock, {"type": "use_hotbar", "slot": number_keys.index(event.key)})

            with self.lock:
                state = dict(self.state)

            players = {player["id"]: player for player in state.get("players", [])}
            you = players.get(self.player_id)

            if not you:
                screen.fill((50, 50, 50))
                self.txt(screen, font, "CONNECTING...", (width // 2, height // 2), anchor="center")
                pygame.display.flip()
                continue

            close_rect = pygame.Rect(12, height - 46, 34, 30)
            if clicked and close_rect.collidepoint(mouse):
                self.running = False
                continue

            field = state.get("field", [])
            key = str(field)

            if field and key != field_text:
                field_surface = pygame.Surface((len(field[0]) * 100, len(field) * 100), pygame.SRCALPHA)

                for row_index, row in enumerate(field):
                    for column_index, (name, rot) in enumerate(row):
                        field_surface.blit(pygame.transform.rotate(images[name], -rot * 90), (column_index * 100, row_index * 100))

                field_text = key

            camera_x, camera_y = you["x"], you["y"]
            target = pygame.Vector2(0, -1).angle_to((width // 2 - mouse[0], mouse[1] - height // 2))
            keys = pygame.key.get_pressed()
            over = state.get("match_over", False)
            input_timer += dt

            if input_timer >= 1 / 30 and not over and state.get("match_started", False):
                send_json(self.sock, {
                    "type": "input",
                    "left": keys[pygame.K_a] or keys[pygame.K_LEFT],
                    "right": keys[pygame.K_d] or keys[pygame.K_RIGHT],
                    "forward": keys[pygame.K_w] or keys[pygame.K_UP],
                    "backward": keys[pygame.K_s] or keys[pygame.K_DOWN],
                    "aim": target
                })
                input_timer = 0

            shot_cooldown = 0.5 / (3.0 if you.get("rapid_remaining", 0) > 0 else 1.0)
            if clicked and not shop_open and you["alive"] and not over and state.get("match_started", False) and time.time() - self.last_shot >= shot_cooldown:
                send_json(self.sock, {"type": "shoot"})
                self.last_shot = time.time()

            screen.fill((50, 50, 50))

            if field_surface:
                screen.blit(field_surface, (width // 2 - 150 - camera_x * 100, height // 2 - 150 - camera_y * 100))

            for ammo in state.get("ammo_positions", []):
                position = ((ammo[0] - camera_x) * 100 + width // 2, (ammo[1] - camera_y) * 100 + height // 2)
                screen.blit(images["ammo"], images["ammo"].get_rect(center=position))

            for scrap in state.get("scrap_positions", []):
                position = ((scrap[0] - camera_x) * 100 + width // 2, (scrap[1] - camera_y) * 100 + height // 2)
                screen.blit(images["scrap"], images["scrap"].get_rect(center=position))

            for health in state.get("health_positions", []):
                position = ((health[0] - camera_x) * 100 + width // 2, (health[1] - camera_y) * 100 + height // 2)
                screen.blit(images["health"], images["health"].get_rect(center=position))

            for bullet in state.get("bullets", []):
                image = pygame.transform.rotate(images["bullet"], bullet["direction"])
                position = ((bullet["x"] - camera_x) * 100 + width // 2, (bullet["y"] - camera_y) * 100 + height // 2)
                screen.blit(image, image.get_rect(center=position))

            for impact in state.get("impacts", []):
                image = pygame.transform.rotate(images["bullet_break"], impact["direction"])
                position = ((impact["x"] - camera_x) * 100 + width // 2, (impact["y"] - camera_y) * 100 + height // 2)
                screen.blit(image, image.get_rect(center=position))

            for player in players.values():
                if not player["alive"]:
                    continue

                player_x = (player["x"] - camera_x) * 100 + width // 2
                player_y = (player["y"] - camera_y) * 100 + height // 2
                tread = pygame.transform.rotate(images["tread" + str(int(player.get("tread_frame", 0)) % 3 + 1)], player["tread_rot"])
                screen.blit(tread, tread.get_rect(center=(player_x, player_y)))
                self.blit_body(screen, images[player["color"]], (player_x, player_y), player["head_rot"])
                free_for_all = state.get("free_for_all", False)
                name_color = (255, 220, 120) if free_for_all and player["id"] == you["id"] else ((255, 120, 120) if free_for_all else ((100, 200, 255) if player["team"] == you["team"] else (255, 120, 120)))
                self.txt(screen, small, player["name"], (player_x, player_y + 58), name_color, "midtop")

            stats_rect = pygame.Rect(15, 15, 330, 142)
            self.transparent_box(screen, stats_rect, 128)
            self.txt(screen, font, "HEALTH: " + str(you["health"]), (30, 28))
            self.txt(screen, font, "YOUR AMMO: " + str(you["ammo"]), (30, 58))
            self.txt(screen, font, "YOUR SCRAP: " + str(you.get("scrap", 0)), (30, 88))
            if not state.get("free_for_all", False):
                self.txt(screen, font, "TEAM SCRAP: " + str(state.get("team_scrap", 0)), (30, 118))
            else:
                self.txt(screen, font, "MODE: FREE-FOR-ALL", (30, 118))

            remaining = max(0, int(math.ceil(state.get("time_remaining", 0))))
            minutes = remaining // 60
            seconds = remaining % 60
            timer_text = str(minutes) + ":" + str(seconds).zfill(2)
            self.txt(screen, timer_font, timer_text, (width // 2, 38), anchor="midtop")

            countdown = state.get("countdown_remaining", 0)
            if not state.get("match_started", False):
                lobby_w = min(720, width - 80)
                lobby_h = min(500, height - 180)
                lobby_rect = pygame.Rect(width // 2 - lobby_w // 2, height // 2 - lobby_h // 2, lobby_w, lobby_h)
                self.transparent_box(screen, lobby_rect, 220)
                self.txt(screen, title, "LOBBY", (width // 2, lobby_rect.y + 28), anchor="midtop")
                self.txt(screen, small, str(len(players)) + "/" + str(state.get("max_players", 8)) + " PLAYERS", (width // 2, lobby_rect.y + 82), (220, 220, 220), "midtop")

                y0 = lobby_rect.y + 125
                free_for_all = state.get("free_for_all", False)
                sort_key = (lambda item: item["id"]) if free_for_all else (lambda item: (item["team"], item["id"]))
                for index, player in enumerate(sorted(players.values(), key=sort_key)):
                    team_text = "FREE-FOR-ALL" if free_for_all else "TEAM " + str(player["team"] + 1)
                    host_mark = " [HOST]" if player["id"] == state.get("host_id") else ""
                    line = player["name"] + host_mark + "   " + team_text
                    self.txt(screen, small, line, (lobby_rect.x + 40, y0 + index * 28))

                if countdown > 0:
                    self.txt(screen, title, str(max(1, int(math.ceil(countdown)))), (width // 2, lobby_rect.bottom - 95), (255, 220, 120), "center")
                elif self.player_id == state.get("host_id"):
                    start_rect = pygame.Rect(width // 2 - 150, lobby_rect.bottom - 90, 300, 50)
                    ready = len(players) >= 2 and (state.get("free_for_all", False) or len({p["team"] for p in players.values()}) >= 2)
                    pygame.draw.rect(screen, (95, 95, 95) if ready else (55, 55, 55), start_rect)
                    pygame.draw.rect(screen, (220, 220, 220), start_rect, 2)
                    need_text = "NEED 2 PLAYERS" if state.get("free_for_all", False) else "NEED BOTH TEAMS"
                    self.txt(screen, font, "START GAME" if ready else need_text, start_rect.center, anchor="center")
                    if clicked and ready and start_rect.collidepoint(mouse):
                        send_json(self.sock, {"type": "start_match"})
                else:
                    self.txt(screen, small, "WAITING FOR HOST TO START", (width // 2, lobby_rect.bottom - 65), (255, 220, 120), "center")

            # Shop button and 10-slot hotbar. B also toggles the shop; 1-9 and 0 use slots 1-10.
            shop_button = pygame.Rect(24, 170, 48, 48)
            pygame.draw.rect(screen, (55, 55, 55), shop_button)
            pygame.draw.rect(screen, (220, 220, 220), shop_button, 2)
            screen.blit(images["shop_icon"], images["shop_icon"].get_rect(center=shop_button.center))
            if clicked and shop_button.collidepoint(mouse):
                shop_open = not shop_open

            hotbar = list(you.get("hotbar", []))[:10]
            slot_size = 48
            gap = 5
            total_w = slot_size * 10 + gap * 9
            hotbar_x = width // 2 - total_w // 2
            hotbar_y = height - 64
            for slot in range(10):
                rect = pygame.Rect(hotbar_x + slot * (slot_size + gap), hotbar_y, slot_size, slot_size)
                pygame.draw.rect(screen, (30, 30, 30), rect)
                pygame.draw.rect(screen, (210, 210, 210), rect, 2)
                key_label = str(slot + 1) if slot < 9 else "0"
                self.txt(screen, small, key_label, (rect.x + 4, rect.y + 3), (180, 180, 180))
                if slot < len(hotbar):
                    item = hotbar[slot]
                    icon = images.get(item)
                    if icon:
                        screen.blit(icon, icon.get_rect(center=(rect.centerx, rect.centery + 4)))

            effects = []
            if you.get("shield_remaining", 0) > 0:
                effects.append("SHIELD " + str(int(math.ceil(you["shield_remaining"]))) + "s")
            if you.get("rapid_remaining", 0) > 0:
                effects.append("RAPID " + str(int(math.ceil(you["rapid_remaining"]))) + "s")
            if you.get("engine_stacks", 0) > 0:
                effects.append("ENGINE x" + str(you["engine_stacks"]))
            if you.get("explosive_rounds", 0) > 0:
                effects.append("EXPLOSIVE " + str(you["explosive_rounds"]))
            if effects:
                self.txt(screen, small, " | ".join(effects), (width // 2, hotbar_y - 24), (255, 220, 120), "midtop")

            if shop_open and not over:
                panel = pygame.Rect(width // 2 - 390, height // 2 - 300, 780, 600)
                self.transparent_box(screen, panel, 235)
                self.txt(screen, title, "SCRAP SHOP", (width // 2, panel.y + 24), anchor="midtop")
                self.txt(screen, small, "SCRAP: " + str(you.get("scrap", 0)) + "   HOTBAR: " + str(len(hotbar)) + "/10   [B] CLOSE", (width // 2, panel.y + 78), (220, 220, 220), "midtop")
                row_y = panel.y + 115
                for index, (item, label, effect, price) in enumerate(shop_items):
                    row = pygame.Rect(panel.x + 28, row_y + index * 70, panel.width - 56, 56)
                    affordable = you.get("scrap", 0) >= price and len(hotbar) < 10 and you.get("alive", False)
                    pygame.draw.rect(screen, (72, 72, 72) if affordable else (42, 42, 42), row)
                    pygame.draw.rect(screen, (220, 220, 220), row, 2)
                    icon = images[item]
                    screen.blit(icon, icon.get_rect(center=(row.x + 35, row.centery)))
                    self.txt(screen, small, label, (row.x + 68, row.y + 8), (255, 255, 255) if affordable else (130, 130, 130))
                    self.txt(screen, small, effect, (row.x + 68, row.y + 31), (190, 190, 190))
                    price_text = str(price) + " SCRAP"
                    self.txt(screen, small, price_text, (row.right - 18, row.centery), (120, 255, 120) if affordable else (130, 130, 130), "midright")
                    if clicked and row.collidepoint(mouse) and affordable:
                        send_json(self.sock, {"type": "buy_item", "item": item})
                        purchase_flash = 0.28
                if len(hotbar) >= 10:
                    self.txt(screen, small, "HOTBAR FULL", (width // 2, panel.bottom - 34), (255, 140, 120), "midbottom")

            if purchase_flash > 0:
                cx, cy = width // 2, height // 2 - 315
                size = int(18 + 28 * (purchase_flash / 0.28))
                points = [(cx, cy - size), (cx + size // 3, cy - size // 3), (cx + size, cy), (cx + size // 3, cy + size // 3), (cx, cy + size), (cx - size // 3, cy + size // 3), (cx - size, cy), (cx - size // 3, cy - size // 3)]
                pygame.draw.polygon(screen, (255, 210, 40), points)
                pygame.draw.polygon(screen, (255, 120, 20), points, 3)
                self.txt(screen, small, "PURCHASED", (cx, cy), (30, 30, 30), "center")

            join_code = state.get("join_code", self.join_code)
            self.txt(screen, small, "JOIN CODE: " + join_code, (width - 20, 20), (220, 220, 220), "topright")

            chat = pygame.Rect(width - 490, height - 190, 470, 170)
            self.transparent_box(screen, chat, 128)
            self.txt(screen, small, "GAME CHAT", (chat.x + 12, chat.y + 10))

            for index, message in enumerate(state.get("chat", [])[-7:]):
                self.txt(screen, small, message, (chat.x + 12, chat.y + 35 + index * 18))

            max_health = max(1, int(state.get("settings", {}).get("max_health", 100)))
            alpha = max(0, min(100, int(100 * (1 - you["health"] / max_health))))
            overlay.fill((255, 0, 0, alpha))
            screen.blit(overlay, (0, 0))

            if not you["alive"] and not over:
                shade = pygame.Surface((width, height), pygame.SRCALPHA)
                shade.fill((0, 0, 0, 150))
                screen.blit(shade, (0, 0))
                self.txt(screen, title, "YOU DIED!", (width // 2, height // 2 - 45), anchor="center")
                respawn_left = max(0, int(math.ceil(you.get("respawn_remaining", 0))))
                self.txt(screen, font, "RESPAWNING IN " + str(respawn_left) + "...", (width // 2, height // 2 + 30), (230, 230, 230), "center")

            # Hold TAB for player/network info.
            if keys[pygame.K_TAB]:
                free_for_all = state.get("free_for_all", False)
                rows = sorted(players.values(), key=(lambda item: item["name"].lower()) if free_for_all else (lambda item: (item["team"], item["name"].lower())))
                box_w = 520
                box_h = 70 + max(1, len(rows)) * 28
                box = pygame.Rect(width // 2 - box_w // 2, 110, box_w, box_h)
                self.transparent_box(screen, box, 225)
                self.txt(screen, font, "PLAYERS / PING", (width // 2, box.y + 16), anchor="midtop")
                for index, row in enumerate(rows):
                    ping = str(row.get("ping", 0)) + " ms"
                    line = row["name"] + ("   FFA" if free_for_all else "   TEAM " + str(row["team"] + 1))
                    self.txt(screen, small, line, (box.x + 22, box.y + 55 + index * 28))
                    self.txt(screen, small, ping, (box.right - 22, box.y + 55 + index * 28), anchor="topright")

            # Hold ` or ~ for the scoreboard.
            if keys[pygame.K_BACKQUOTE]:
                rows = state.get("rankings", [])
                box_w = 650
                box_h = 75 + max(1, len(rows)) * 30
                box = pygame.Rect(width // 2 - box_w // 2, 110, box_w, box_h)
                self.transparent_box(screen, box, 230)
                self.txt(screen, font, "SCOREBOARD", (width // 2, box.y + 16), anchor="midtop")
                self.txt(screen, small, "PLAYER", (box.x + 25, box.y + 52))
                self.txt(screen, small, "MODE" if state.get("free_for_all", False) else "TEAM", (box.x + 335, box.y + 52))
                self.txt(screen, small, "KILLS", (box.x + 430, box.y + 52))
                self.txt(screen, small, "DEATHS", (box.x + 525, box.y + 52))
                for index, row in enumerate(rows):
                    row_y = box.y + 80 + index * 30
                    self.txt(screen, small, row["name"], (box.x + 25, row_y))
                    self.txt(screen, small, "FFA" if state.get("free_for_all", False) else row["team"] + 1, (box.x + 350, row_y))
                    self.txt(screen, small, row["kills"], (box.x + 445, row_y))
                    self.txt(screen, small, row["deaths"], (box.x + 550, row_y))

            # Always-visible FPS and close button.
            pygame.draw.rect(screen, (80, 80, 80), close_rect)
            pygame.draw.rect(screen, (220, 220, 220), close_rect, 2)
            self.txt(screen, small, "X", close_rect.center, anchor="center")
            self.txt(screen, small, "FPS: " + str(round(clock.get_fps())), (55, height - 36), (220, 220, 220))

            if you.get("spawn_protected"):
                self.txt(screen, small, "SPAWN PROTECTION", (width // 2, height - 35), (255, 220, 120), "midbottom")

            if over:
                shade = pygame.Surface((width, height), pygame.SRCALPHA)
                shade.fill((0, 0, 0, 210))
                screen.blit(shade, (0, 0))
                winner = state.get("winner")
                if state.get("free_for_all", False):
                    heading = "DRAW!" if winner == -1 else ("YOU WON!" if winner == you["id"] else "MATCH OVER")
                else:
                    heading = "DRAW!" if winner == -1 else ("YOUR TEAM WON!" if winner == you["team"] else "YOUR TEAM LOST!")
                self.txt(screen, title, heading, (width // 2, 55), anchor="midtop")
                rematch = max(0, int(math.ceil(state.get("rematch_time_remaining", 0))))
                self.txt(screen, small, "NEXT GAME IN " + str(rematch) + "s", (width // 2, height - 28), (210, 210, 210), "midbottom")
                scrap_totals = state.get("team_scrap_totals", [0, 0])
                if not state.get("free_for_all", False):
                    self.txt(screen, font, "TEAM 1 SCRAP: " + str(scrap_totals[0]) + "   TEAM 2 SCRAP: " + str(scrap_totals[1]), (width // 2, 110), anchor="midtop")
                else:
                    self.txt(screen, font, "FREE-FOR-ALL", (width // 2, 110), anchor="midtop")
                self.txt(screen, font, "RANKED BY KILLS - DEATHS", (width // 2, 145), anchor="midtop")
                rows = state.get("rankings", [])
                table_width = 830
                x = width // 2 - table_width // 2
                y = 185
                pygame.draw.rect(screen, (30, 30, 30), (x, y, table_width, 50 + 30 * max(1, len(rows))))
                pygame.draw.rect(screen, (220, 220, 220), (x, y, table_width, 50 + 30 * max(1, len(rows))), 2)

                for label, offset in [("RANK", 15), ("PLAYER", 105), (("MODE" if state.get("free_for_all", False) else "TEAM"), 390), ("KILLS", 500), ("DEATHS", 590), ("DIFF", 685), ("SCRAP", 760)]:
                    self.txt(screen, small, label, (x + offset, y + 15), anchor="midtop")

                for index, row in enumerate(rows):
                    row_y = y + 50 + index * 30

                    for value, offset in [(index + 1, 15), (row["name"], 105), (("FFA" if state.get("free_for_all", False) else row["team"] + 1), 390), (row["kills"], 500), (row["deaths"], 590), (row["difference"], 685), (row.get("scrap", 0), 760)]:
                        self.txt(screen, small, value, (x + offset, row_y))

                exit_rect = pygame.Rect(width - 220, height - 80, 190, 50)
                pygame.draw.rect(screen, (105, 105, 105) if exit_rect.collidepoint(mouse) else (70, 70, 70), exit_rect)
                pygame.draw.rect(screen, (230, 230, 230), exit_rect, 2)
                self.txt(screen, font, "EXIT", exit_rect.center, anchor="center")

                if clicked and exit_rect.collidepoint(mouse):
                    self.running = False

            pygame.draw.rect(screen, (80, 80, 80), close_rect)
            pygame.draw.rect(screen, (220, 220, 220), close_rect, 2)
            self.txt(screen, small, "X", close_rect.center, anchor="center")
            self.txt(screen, small, "FPS: " + str(round(clock.get_fps())), (55, height - 36), (220, 220, 220))

            pygame.display.flip()

        try:
            self.sock.close()
        except OSError:
            pass

        pygame.quit()