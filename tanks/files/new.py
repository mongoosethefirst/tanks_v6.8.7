# -*- coding: utf-8 -*-
import math, random, time, pygame
from paths import image_path, font_path
from server import GameServer
from network import TCP_PORT

players = {}
field = []
ammo_positions = []
server = None
host_name = ""
host_color = "red"
host_join_code = ""
host_port = TCP_PORT

pygame.init()
screen = pygame.display.set_mode((0, 0))
running = True
clock = pygame.time.Clock()
width, height = screen.get_size()
frames = 0
color = 0
colors = ["red", "orange", "yellow", "green", "blue", "purple", "pink"]
font = pygame.font.Font(font_path(), 20)
small_font = pygame.font.Font(font_path(), 12)
tiny_font = pygame.font.Font(font_path(), 10)
title_font = pygame.font.Font(font_path(), 26)
images = {}

for number in range(1, 4):
    image = pygame.image.load(image_path("tread" + str(number) + ".png")).convert_alpha()
    images["tread" + str(number)] = pygame.transform.scale(image, (80, 80))

for color_name in colors:
    image = pygame.image.load(image_path(color_name + "body.png")).convert_alpha()
    images[color_name] = pygame.transform.scale(image, (106, 160))

left = pygame.transform.scale(pygame.image.load(image_path("left.png")).convert_alpha(), (80, 80))
right = pygame.transform.scale(pygame.image.load(image_path("right.png")).convert_alpha(), (80, 80))
play = pygame.transform.scale(pygame.image.load(image_path("play.png")).convert_alpha(), (90, 80))

username_rect = pygame.Rect((width // 2) - 205, (height // 2) + 170, 410, 30)
timer_rect = pygame.Rect((width // 2) - 205, (height // 2) + 260, 410, 30)
text = "PLAYER" + str(random.randint(1111, 9999))
timer_text = "10"
active = "username"
status = ""
page = 0

scrap_factor = 1.0
ammo_factor = 1.0
health_factor = 1.0
max_players = 8
starting_ammo = 30
max_health = 100
respawn_seconds = 3
friendly_fire = False
free_for_all = False

slider_width = min(520, width - 180)
slider_x = width // 2 - slider_width // 2

def factor_from_x(x):
    ratio = max(0.0, min(1.0, (x - slider_x) / slider_width))
    return round((0.1 + ratio * 4.9) * 10) / 10

def factor_x(value):
    return slider_x + int(((value - 0.1) / 4.9) * slider_width)

def players_from_x(x):
    ratio = max(0.0, min(1.0, (x - slider_x) / slider_width))
    index = round(ratio * 7)
    return 2 + index * 2

def players_x(value):
    return slider_x + int(((value - 2) / 14) * slider_width)

def stepped_from_x(x, low, high, step):
    ratio = max(0.0, min(1.0, (x - slider_x) / slider_width))
    count = round((high - low) / step)
    return low + round(ratio * count) * step

def stepped_x(value, low, high):
    return slider_x + int(((value - low) / (high - low)) * slider_width)

def map_size_for(value):
    extra_pairs = (value - 2) // 2
    return max(20, round(20 * math.sqrt(1 + 0.25 * extra_pairs)))

def draw_slider(label, value_text, y, knob_x):
    label_surface = small_font.render(label, True, (255, 255, 255))
    screen.blit(label_surface, (slider_x, y - 30))
    value_surface = small_font.render(value_text, True, (255, 220, 120))
    screen.blit(value_surface, value_surface.get_rect(topright=(slider_x + slider_width, y - 30)))
    pygame.draw.line(screen, (130, 130, 130), (slider_x, y), (slider_x + slider_width, y), 7)
    pygame.draw.circle(screen, (255, 255, 255), (knob_x, y), 11)

while running:
    dt = clock.tick(60) / 1000
    clicked = False
    held = pygame.mouse.get_pressed()[0]

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            clicked = True
            if page == 0:
                if username_rect.collidepoint(event.pos):
                    active = "username"
                elif timer_rect.collidepoint(event.pos):
                    active = "timer"
                else:
                    active = None

        if event.type == pygame.KEYDOWN and page == 0:
            if active == "username":
                if event.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                elif event.key != pygame.K_RETURN and len(text) < 20 and event.unicode.isprintable():
                    text += event.unicode
            elif active == "timer":
                if event.key == pygame.K_BACKSPACE:
                    timer_text = timer_text[:-1]
                elif event.key != pygame.K_RETURN and event.unicode.isdigit() and len(timer_text) < 3:
                    timer_text += event.unicode

    screen.fill((50, 50, 50))
    x, y = pygame.mouse.get_pos()

    close_rect = pygame.Rect(12, height - 46, 34, 30)
    pygame.draw.rect(screen, (80, 80, 80), close_rect)
    pygame.draw.rect(screen, (220, 220, 220), close_rect, 2)
    close_surface = small_font.render("X", True, (255, 255, 255))
    screen.blit(close_surface, close_surface.get_rect(center=close_rect.center))
    fps_text = tiny_font.render("FPS: " + str(round(clock.get_fps())), True, (220, 220, 220))
    screen.blit(fps_text, (55, height - 36))

    if clicked and close_rect.collidepoint(x, y):
        running = False
        continue

    if page == 0:
        tread_name = "tread" + str(round(frames / 20) % 3 + 1)
        screen.blit(images[tread_name], ((width // 2) - 40, (height // 2) - 40))

        left_rect = pygame.Rect((width // 2) - 180, (height // 2) - 40, 80, 80)
        right_rect = pygame.Rect((width // 2) + 100, (height // 2) - 40, 80, 80)
        play_rect = pygame.Rect((width // 2) - 45, (height // 2) + 340, 90, 80)
        screen.blit(left, left_rect)
        screen.blit(right, right_rect)
        screen.blit(play, play_rect)

        pygame.draw.rect(screen, (255, 255, 255) if active == "username" else (150, 150, 150), username_rect, 2)
        pygame.draw.rect(screen, (255, 255, 255) if active == "timer" else (150, 150, 150), timer_rect, 2)
        screen.blit(font.render(text, True, (255, 255, 255)), (username_rect.x + 5, username_rect.y + 5))
        timer_surface = font.render(timer_text or "0", True, (255, 255, 255))
        screen.blit(timer_surface, timer_surface.get_rect(center=timer_rect.center))
        nickname_label = font.render("Enter Nickname", True, (255, 255, 255))
        minutes_label = font.render("Match Minutes", True, (255, 255, 255))
        screen.blit(nickname_label, nickname_label.get_rect(center=(width // 2, username_rect.y - 30)))
        screen.blit(minutes_label, minutes_label.get_rect(center=(width // 2, timer_rect.y - 30)))

        join_text = "JOIN CODE: " + (host_join_code or "------")
        join_surface = font.render(join_text, True, (255, 255, 255))
        screen.blit(join_surface, join_surface.get_rect(center=(width // 2, timer_rect.y + 60)))

        if clicked:
            if left_rect.collidepoint(x, y):
                color = (color - 1) % 7
            elif right_rect.collidepoint(x, y):
                color = (color + 1) % 7
            elif play_rect.collidepoint(x, y):
                minutes = int(timer_text or 0)
                if minutes < 1 or minutes > 120:
                    status = "CHOOSE 1-120 MINUTES"
                else:
                    page = 1
                    status = ""

        body = images[colors[color]]
        screen.blit(body, body.get_rect(center=(width // 2, height // 2)))

        if status:
            status_surface = small_font.render(status, True, (255, 180, 120))
            screen.blit(status_surface, status_surface.get_rect(center=(width // 2, height // 2 + 445)))

    else:
        title = title_font.render("GAME SETTINGS", True, (255, 255, 255))
        screen.blit(title, title.get_rect(center=(width // 2, 65)))
        subtitle = tiny_font.render("Spawn multipliers are applied on top of normal player scaling.", True, (190, 190, 190))
        screen.blit(subtitle, subtitle.get_rect(center=(width // 2, 100)))

        ys = [155, 235, 315, 395, 475, 555, 635]
        draw_slider("SCRAP SPAWN", f"{scrap_factor:.1f}x", ys[0], factor_x(scrap_factor))
        draw_slider("AMMO SPAWN", f"{ammo_factor:.1f}x", ys[1], factor_x(ammo_factor))
        draw_slider("HEALTH SPAWN", f"{health_factor:.1f}x", ys[2], factor_x(health_factor))
        draw_slider("MAX PLAYERS", str(max_players), ys[3], players_x(max_players))
        draw_slider("STARTING AMMO", str(starting_ammo), ys[4], stepped_x(starting_ammo, 0, 100))
        draw_slider("MAX HEALTH", str(max_health), ys[5], stepped_x(max_health, 50, 250))
        draw_slider("RESPAWN TIME", str(respawn_seconds) + "s", ys[6], stepped_x(respawn_seconds, 1, 10))

        if held:
            if abs(y - ys[0]) <= 22 and slider_x - 15 <= x <= slider_x + slider_width + 15:
                scrap_factor = factor_from_x(x)
            elif abs(y - ys[1]) <= 22 and slider_x - 15 <= x <= slider_x + slider_width + 15:
                ammo_factor = factor_from_x(x)
            elif abs(y - ys[2]) <= 22 and slider_x - 15 <= x <= slider_x + slider_width + 15:
                health_factor = factor_from_x(x)
            elif abs(y - ys[3]) <= 22 and slider_x - 15 <= x <= slider_x + slider_width + 15:
                max_players = players_from_x(x)
            elif abs(y - ys[4]) <= 22 and slider_x - 15 <= x <= slider_x + slider_width + 15:
                starting_ammo = stepped_from_x(x, 0, 100, 5)
            elif abs(y - ys[5]) <= 22 and slider_x - 15 <= x <= slider_x + slider_width + 15:
                max_health = stepped_from_x(x, 50, 250, 10)
            elif abs(y - ys[6]) <= 22 and slider_x - 15 <= x <= slider_x + slider_width + 15:
                respawn_seconds = stepped_from_x(x, 1, 10, 1)

        friendly_rect = pygame.Rect(width // 2 - 350, 685, 330, 42)
        ffa_rect = pygame.Rect(width // 2 + 20, 685, 330, 42)
        pygame.draw.rect(screen, (95, 95, 95), friendly_rect)
        pygame.draw.rect(screen, (95, 95, 95), ffa_rect)
        pygame.draw.rect(screen, (220, 220, 220), friendly_rect, 2)
        pygame.draw.rect(screen, (220, 220, 220), ffa_rect, 2)
        ff_text = "FRIENDLY FIRE: " + ("ON" if friendly_fire else "OFF")
        ffa_text = "FREE-FOR-ALL: " + ("ON" if free_for_all else "OFF")
        ff_surface = small_font.render(ff_text, True, (160, 160, 160) if free_for_all else (255, 255, 255))
        ffa_surface = small_font.render(ffa_text, True, (255, 255, 255))
        screen.blit(ff_surface, ff_surface.get_rect(center=friendly_rect.center))
        screen.blit(ffa_surface, ffa_surface.get_rect(center=ffa_rect.center))

        map_size = map_size_for(max_players)
        mode_text = "FREE-FOR-ALL" if free_for_all else "TEAMS"
        info = tiny_font.render("MODE: " + mode_text + " | MAP: " + str(map_size) + " x " + str(map_size) + " | ammo keeps +0.5x player scaling", True, (200, 200, 200))
        screen.blit(info, info.get_rect(center=(width // 2, 750)))

        back_rect = pygame.Rect(width // 2 - 220, height - 120, 160, 55)
        start_rect = pygame.Rect(width // 2 + 60, height - 120, 160, 55)
        pygame.draw.rect(screen, (90, 90, 90), back_rect)
        pygame.draw.rect(screen, (90, 90, 90), start_rect)
        pygame.draw.rect(screen, (220, 220, 220), back_rect, 2)
        pygame.draw.rect(screen, (220, 220, 220), start_rect, 2)
        back_surface = font.render("BACK", True, (255, 255, 255))
        create_surface = font.render("CREATE", True, (255, 255, 255))
        screen.blit(back_surface, back_surface.get_rect(center=back_rect.center))
        screen.blit(create_surface, create_surface.get_rect(center=start_rect.center))

        if clicked and friendly_rect.collidepoint(x, y) and not free_for_all:
            friendly_fire = not friendly_fire
        elif clicked and ffa_rect.collidepoint(x, y):
            free_for_all = not free_for_all
        elif clicked and back_rect.collidepoint(x, y):
            page = 0
        elif clicked and start_rect.collidepoint(x, y):
            minutes = int(timer_text or 10)
            server = GameServer(
                match_minutes=minutes,
                scrap_spawn_factor=scrap_factor,
                ammo_spawn_factor=ammo_factor,
                health_spawn_factor=health_factor,
                max_players=max_players,
                starting_ammo=starting_ammo,
                max_health=max_health,
                respawn_seconds=respawn_seconds,
                friendly_fire=friendly_fire,
                free_for_all=free_for_all
            )
            server.start()
            time.sleep(0.2)
            host_name = text or "PLAYER"
            host_color = colors[color]
            host_join_code = server.join_code
            field = server.field
            ammo_positions = server.ammo_positions
            running = False
            import play_host

    pygame.display.flip()
    frames += 1

pygame.quit()
