#!/usr/bin/env python3
"""
Atom visualizer — run as a subprocess.
Reads commands from stdin:
    state:listening
    state:thinking
    amp:0.12
"""

import sys
import math
import time
import threading
import os
import pygame

SIZE = 400
CX   = SIZE // 2
CY   = SIZE // 2

COLORS = {
    "idle":      {"ring": (51,  68,  136), "electron": (102, 153, 255), "nucleus": (26,  34,  85)},
    "listening": {"ring": (34,  153, 68),  "electron": (0,   255, 136), "nucleus": (10,  51,  34)},
    "thinking":  {"ring": (153, 102, 34),  "electron": (255, 170, 0),   "nucleus": (51,  34,  0)},
    "speaking":  {"ring": (17,  119, 153), "electron": (0,   204, 255), "nucleus": (0,   34,  51)},
}

ORBITS = [(85, 26, 0), (85, 26, 60), (85, 26, 120)]


def _epos(rx, ry, tilt_deg, t_rad):
    x = rx * math.cos(t_rad)
    y = ry * math.sin(t_rad)
    a = math.radians(tilt_deg)
    return (x * math.cos(a) - y * math.sin(a),
            x * math.sin(a) + y * math.cos(a))


def main():
    state     = "idle"
    amplitude = 0.0

    def read_stdin():
        nonlocal state, amplitude
        for line in sys.stdin:
            line = line.strip()
            if line.startswith("state:"):
                state = line[6:]
            elif line.startswith("amp:"):
                try:
                    amplitude = float(line[4:])
                except ValueError:
                    pass

    threading.Thread(target=read_stdin, daemon=True).start()

    os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "100,100")
    pygame.init()
    screen = pygame.display.set_mode((SIZE, SIZE + 50))
    pygame.display.set_caption("Jarvis")
    clock  = pygame.time.Clock()
    font   = pygame.font.SysFont("Helvetica", 16, bold=True)

    angle  = 0.0
    smooth = 0.0

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)

        # synthetic amplitude for non-mic states
        t   = time.time()
        amp = amplitude
        if state == "thinking":
            amp = 0.20 + 0.15 * abs(math.sin(t * 3.0))
        elif state == "speaking":
            amp = 0.28 + 0.22 * abs(math.sin(t * 7.0))
        elif state == "idle":
            amp = 0.06 + 0.04 * abs(math.sin(t * 1.2))

        smooth += (amp - smooth) * 0.14
        s       = smooth

        speed  = 4.0 if state == "thinking" else 1.5
        angle  = (angle + speed) % 360
        scale  = 1.0 + s * 0.40
        c      = COLORS.get(state, COLORS["idle"])

        screen.fill((0, 0, 0))

        # orbit rings
        for rx0, ry0, tilt in ORBITS:
            rx, ry = rx0 * scale, ry0 * scale
            pts = []
            for i in range(61):
                dx, dy = _epos(rx, ry, tilt, math.radians(i * 6))
                pts.append((CX + dx, CY + dy))
            pygame.draw.lines(screen, c["ring"], True, pts, 2)

        # electrons
        for i, (rx0, ry0, tilt) in enumerate(ORBITS):
            rx, ry = rx0 * scale, ry0 * scale
            dx, dy = _epos(rx, ry, tilt, math.radians(angle + i * 120))
            ex, ey = int(CX + dx), int(CY + dy)
            r = int(8 + s * 6)
            pygame.draw.circle(screen, c["electron"], (ex, ey), r)
            pygame.draw.circle(screen, (255, 255, 255), (ex, ey), r, 1)

        # nucleus glow
        r_n = int(22 + s * 20)
        for layer in range(3, 0, -1):
            pygame.draw.circle(screen, c["ring"], (CX, CY), r_n + layer * 7, 1)
        pygame.draw.circle(screen, c["nucleus"], (CX, CY), r_n)
        pygame.draw.circle(screen, c["electron"], (CX, CY), r_n, 3)

        # label
        labels = {"idle": "Idle", "listening": "Listening...",
                  "thinking": "Thinking...", "speaking": "Speaking..."}
        lbl = font.render(labels.get(state, ""), True, c["electron"])
        screen.blit(lbl, (CX - lbl.get_width() // 2, SIZE + 17))

        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    main()
