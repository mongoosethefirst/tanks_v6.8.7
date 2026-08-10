# -*- coding: utf-8 -*-
import time, pygame
from paths import image_path, font_path
from network import GAME_VERSION

pygame.init()

screen = pygame.display.set_mode((0, 0))

running = True
fps = 60
clock = pygame.time.Clock()
width, height = screen.get_size()
mouse_down = False

new_off = pygame.image.load(image_path("new_off.png")).convert_alpha()
new_off = pygame.transform.scale(new_off, (150, 30))
new_on = pygame.image.load(image_path("new_on.png")).convert_alpha()
new_on = pygame.transform.scale(new_on, (150, 30))
join_off = pygame.image.load(image_path("join_off.png")).convert_alpha()
join_off = pygame.transform.scale(join_off, (150, 30))
join_on = pygame.image.load(image_path("join_on.png")).convert_alpha()
join_on = pygame.transform.scale(join_on, (150, 30))

icon = pygame.image.load(image_path("icon.png")).convert_alpha()
icon = pygame.transform.scale(icon, (1000, 600))

version_font = pygame.font.Font(font_path(), 16)
version_text = version_font.render("V" + GAME_VERSION, True, (255, 255, 255))

while running:
    clicked = False

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            clicked = True

    screen.fill((50, 50, 50))

    x, y = pygame.mouse.get_pos()

    close_rect = pygame.Rect(12, height - 46, 34, 30)
    pygame.draw.rect(screen, (80, 80, 80), close_rect)
    pygame.draw.rect(screen, (220, 220, 220), close_rect, 2)
    close_surface = version_font.render("X", True, (255, 255, 255))
    screen.blit(close_surface, close_surface.get_rect(center=close_rect.center))
    fps_surface = version_font.render("FPS: " + str(round(clock.get_fps())), True, (220, 220, 220))
    screen.blit(fps_surface, (55, height - 38))
    if clicked and close_rect.collidepoint(x, y):
        running = False
        continue

    new_rect = pygame.Rect((width//2) - 75, (height//2) - 15, 150, 30)
    join_rect = pygame.Rect((width//2) - 75, (height//2) + 30, 150, 30)

    if new_rect.collidepoint(x, y):
        screen.blit(new_on, new_rect)
        if clicked:
            running = False
            import new
    else:
        screen.blit(new_off, new_rect)

    if join_rect.collidepoint(x, y):
        screen.blit(join_on, join_rect)
        if clicked:
            running = False
            import join
    else:
        screen.blit(join_off, join_rect)

    screen.blit(icon, ((width//2) - 500, -120))
    screen.blit(version_text, (width - version_text.get_width() - 20, height - version_text.get_height() - 20))

    pygame.display.flip()
    clock.tick(fps)

pygame.quit()