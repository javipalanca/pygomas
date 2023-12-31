#!/usr/bin/env python
# -*- coding: UTF8 -*-
import argparse
import copy
import math
import os
import socket
import sys
import traceback

import pygame
from pygame import gfxdraw

objective_x = -1
objective_y = -1
allied_base = None
axis_base = None
graph = {}
agents = {}
dins = {}
factor = 2
screen = None
font = None
maps_path = None

iteration = 0


tile_size = 24
horizontal_tiles = 32
vertical_tiles = 32

map_width = tile_size * horizontal_tiles
map_height = tile_size * vertical_tiles

xdesp = 0
ydesp = 0


def agl_parse(data):
    global allied_base
    global axis_base
    global objective_x
    global objective_y
    global agents
    global dins

    dins = {}
    agl = data.split()
    nagents = int(agl[1])
    agl = agl[2:]
    separator = nagents * 15
    agent_data = agl[:separator]
    din_data = agl[separator:]
    for i in range(nagents):
        agents[agent_data[0]] = {
            "type": agent_data[1],
            "team": agent_data[2],
            "health": agent_data[3],
            "ammo": agent_data[4],
            "carrying": agent_data[5],
            "posx": agent_data[6].strip("(,)"),
            "posy": agent_data[7].strip("(,)"),
            "posz": agent_data[8].strip("(,)"),
            "angx": agent_data[12].strip("(,)"),
            "angy": agent_data[13].strip("(,)"),
            "angz": agent_data[14].strip("(,)"),
        }
        agent_data = agent_data[15:]

    ndin = int(din_data[0])
    din_data = din_data[1:]
    for din in range(ndin):
        dins[din_data[0]] = {
            "type": din_data[1],
            "posx": din_data[2].strip("(,)"),
            "posy": din_data[3].strip("(,)"),
            "posz": din_data[4].strip("(,)"),
        }
        din_data = din_data[5:]


def draw2():

    global agents
    global factor
    global xdesp
    global ydesp
    global tile_size
    global iteration
    global screen
    global font

    events = pygame.event.get()
    for event in events:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                xdesp += tile_size
            if event.key == pygame.K_RIGHT:
                xdesp -= tile_size
            if event.key == pygame.K_DOWN:
                ydesp -= tile_size
            if event.key == pygame.K_UP:
                ydesp += tile_size
            if event.key == pygame.K_x:
                tile_size += 2
            if event.key == pygame.K_z:
                tile_size -= 2

    # Clear screen
    color_background = (0, 0, 0)
    pygame.draw.rect(screen, color_background, (0, 0, map_width, map_height))

    # Draw Map
    color_wall = (100, 100, 100)
    for y in range(0, len(list(graph.items()))):
        for x in range(0, 32):
            try:
                if list(graph.items())[y][1][x] == "*":
                    pygame.draw.rect(
                        screen,
                        color_wall,
                        (
                            x * tile_size + xdesp,
                            y * tile_size + ydesp,
                            tile_size,
                            tile_size,
                        ),
                    )
            except:
                pass

    # Draw bases
    if allied_base is not None:
        color = (255, 0, 0)
        xpos = int(allied_base[0]) * tile_size + xdesp
        ypos = int(allied_base[1]) * tile_size + ydesp
        xwidth = int(allied_base[2]) * tile_size - xpos + tile_size + xdesp
        ywidth = int(allied_base[3]) * tile_size - ypos + tile_size + ydesp

        pygame.draw.rect(screen, color, (xpos, ypos, xwidth, ywidth))

    if axis_base is not None:
        color = (0, 0, 255)
        xpos = int(axis_base[0]) * tile_size + xdesp
        ypos = int(axis_base[1]) * tile_size + ydesp
        xwidth = int(axis_base[2]) * tile_size - xpos + tile_size + xdesp
        ywidth = int(axis_base[3]) * tile_size - ypos + tile_size + ydesp

        pygame.draw.rect(screen, color, (xpos, ypos, xwidth, ywidth))

    # Draw items
    for i in range(0, len(list(dins.items()))):
        posx = int(float(list(dins.items())[i][1]["posx"]) * (tile_size / 8.0)) + xdesp
        posy = int(float(list(dins.items())[i][1]["posz"]) * (tile_size / 8.0)) + ydesp

        item_type = {"1001": "M", "1002": "A", "1003": "F"}.get(
            list(dins.items())[i][1]["type"], "X"
        )

        color = {
            "1001": (255, 255, 255),
            "1002": (255, 255, 255),
            "1003": (255, 255, 0),
        }.get(list(dins.items())[i][1]["type"], "X")

        pygame.draw.circle(screen, color, [posx, posy], 6)
        text = font.render(item_type, True, (0, 0, 0))
        screen.blit(text, (posx - text.get_width() // 2, posy - text.get_height() // 2))

    # Draw units
    for i in list(agents.items()):
        health = float(i[1]["health"])

        if float(health) > 0:

            carrying = i[1]["carrying"]

            agent_type = {"0": "X", "1": "*", "2": "+", "3": "Y", "4": "^"}.get(
                i[1]["type"], "X"
            )

            team = {"100": (255, 100, 100), "200": (100, 100, 255)}.get(
                i[1]["team"], (255, 255, 0)
            )

            team_aplha = {"100": (255, 100, 100, 100), "200": (100, 100, 255, 100)}.get(
                i[1]["team"], (255, 255, 0, 255)
            )

            ammo = float(i[1]["ammo"])

            posx = int(float(i[1]["posx"]) * tile_size / 8.0) + xdesp
            posy = int(float(i[1]["posz"]) * tile_size / 8.0) + ydesp

            # calcula direccion
            angx = float(i[1]["angx"])
            angy = float(i[1]["angz"])

            if angx == 0:
                div = 1000
            else:
                div = angy / angx

            if angy >= 0 and angx >= 0:  # q1
                angle = math.atan(div) * (180 / math.pi)
            elif angy >= 0 and angx <= 0:  # q2
                angle = math.atan(div) * (180 / math.pi) + 180
            elif angy <= 0 and angx <= 0:  # q3
                angle = math.atan(div) * (180 / math.pi) + 180
            else:  # q4
                angle = math.atan(div) * (180 / math.pi) + 360

            # imprime ficha
            pygame.draw.circle(screen, team, [posx, posy], 8)
            # imprime identificador
            text = font.render(i[0], True, (255, 255, 255))
            screen.blit(
                text,
                (posx - text.get_width() // 2 + 15, posy - text.get_height() // 2 - 15),
            )
            # imprime vida
            pygame.gfxdraw.aacircle(screen, posx, posy, 10, (255, 0, 0))
            pygame.gfxdraw.aacircle(screen, posx, posy, 9, (255, 0, 0))
            pygame.gfxdraw.arc(
                screen, posx, posy, 10, 0, int(health * 3.6) - 1, (0, 255, 0)
            )
            pygame.gfxdraw.arc(
                screen, posx, posy, 9, 0, int(health * 3.6) - 1, (0, 255, 0)
            )
            # imprime municion
            if ammo >= 1:
                pygame.gfxdraw.arc(
                    screen, posx, posy, 6, 0, int(ammo * 3.6) - 1, (255, 255, 255)
                )
                pygame.gfxdraw.arc(
                    screen, posx, posy, 7, 0, int(ammo * 3.6) - 1, (255, 255, 255)
                )

            # lleva la bandera
            if carrying == "1":
                pygame.draw.circle(screen, (255, 255, 0), [posx, posy], 5)

            # imprime cono de vision
            for j in range(0, int(48 * (tile_size / 8)), 1):
                pygame.gfxdraw.arc(
                    screen, posx, posy, j, int(-45 + angle), int(45 + angle), team_aplha
                )

            # imprime funcion
            text = font.render(agent_type, True, (0, 0, 0))
            screen.blit(
                text, (posx - text.get_width() // 2, posy - text.get_height() // 2)
            )

    pygame.display.flip()
    iteration += 1

    agents_json = {}
    for i in list(agents.items()):
        agents_json[i[0]] = i[1]

    items_json = {}
    for i in list(dins.items()):
        items_json[i[0]] = i[1]

    json_data = {"agents": agents_json, "items": items_json}


def loadMap(map_name):
    global allied_base
    global axis_base
    global objective_x
    global objective_y
    global maps_path

    if maps_path is not None:
        path = f"{maps_path}{os.sep}{map_name}{os.sep}{map_name}"
    else:
        this_dir, _ = os.path.split(__file__)
        path = f"{this_dir}{os.sep}maps{os.sep}{map_name}{os.sep}{map_name}"

    mapf = open(f"{path}.txt", "r")
    cost = open(f"{path}_cost.txt", "r")

    for line in mapf.readlines():
        if "pGomas_OBJECTIVE" in line:
            l = line.split()
            objective_x = copy.copy(int(l[1]))
            objective_y = copy.copy(int(l[2]))
        elif "pGomas_SPAWN_ALLIED" in line:
            l = line.split()
            l.pop(0)
            allied_base = copy.copy(l)
        elif "pGomas_SPAWN_AXIS" in line:
            l = line.split()
            l.pop(0)
            axis_base = copy.copy(l)
    mapf.close()

    y = 0
    for line in cost.readlines():
        graph[y] = line.strip("\r\n")
        y += 1
    cost.close()


def main(address="localhost", port=8001, maps=None):
    global f
    global screen
    global font
    global maps_path

    # Main
    maps_path = maps

    # Init pygame
    pygame.init()
    font = pygame.font.SysFont("ttf-font-awesome", 12)

    # Set the height and width of the screen
    size = [map_width, map_height]
    screen = pygame.display.set_mode(size)

    try:
        # Init socket
        s = None
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if s:
            s.connect((address, port))
            rfile = s.makefile("r", -1)
            wfile = s.makefile("w", 20)
            data = rfile.readline()

            wfile.write("READY\n")
            wfile.close()
            in_loop = True
            while in_loop:
                data = ""
                data = rfile.readline()
                if "COM" in data[0:5]:
                    if "Accepted" in data:
                        pass
                    elif "Closed" in data:
                        in_loop = False
                elif "MAP" in data[0:5]:
                    p = data.split()
                    mapname = p[2]
                    loadMap(mapname)
                elif "AGL" in data[0:5]:
                    agl_parse(data)
                elif "TIM" in data[0:5]:
                    pass
                elif "ERR" in data[0:5]:
                    pass
                else:
                    # Unknown message type
                    pass
                draw2()

            # Close socket
            del rfile
            del wfile
            s.close()

    except Exception as e:
        print("Exception", str(e))
        print("-" * 60)
        traceback.print_exc(file=sys.stdout)
        print("-" * 60)

    finally:
        pygame.quit()
        f.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ip", default="localhost", help="Manager's address to connect the render"
    )
    parser.add_argument(
        "--port", default=8001, help="Manager's port to connect the render"
    )
    parser.add_argument(
        "--maps", default=None, help="The path to your custom maps directory"
    )

    args = parser.parse_args()
    main(args.ip, args.port, args.maps)
    sys.exit(0)
