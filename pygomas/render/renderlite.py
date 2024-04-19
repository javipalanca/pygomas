#!/usr/bin/env python
# -*- coding: UTF8 -*-
import argparse
import copy
import curses
import json
import math
import os
import socket
import struct
import sys
import time
import traceback
from itertools import cycle

import msgpack
import pygame
from loguru import logger
from pygame import gfxdraw
from pygame.rect import Rect

from pygomas.agents.bditroop import CLASS_NONE, CLASS_SOLDIER, CLASS_MEDIC, CLASS_ENGINEER, CLASS_FIELDOPS
from pygomas.config import TEAM_AXIS, TEAM_ALLIED, TEAM_NONE
from pygomas.packs.pack import PACK_MEDICPACK, PACK_AMMOPACK, PACK_OBJPACK
from pygomas.server import TCP, Msg

draw_rect = False


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i: i + n]


def get_angle(angx, angy):
    if angx == 0:
        div = 1000
    else:
        div = angy / angx
    if angy >= 0 and angx >= 0:  # q1
        angle = math.atan(div) * (180 / math.pi)
    elif angy >= 0 >= angx:  # q2
        angle = math.atan(div) * (180 / math.pi) + 180
    elif angy <= 0 and angx <= 0:  # q3
        angle = math.atan(div) * (180 / math.pi) + 180
    else:  # q4
        angle = math.atan(div) * (180 / math.pi) + 360
    return angle


class Render(object):
    def __init__(
            self,
            address="localhost",
            port=8001,
            maps=None,
            fps=30,
            text=False,
            replay=False,
            dump=False,
            log="match.log",
            wait_fps=round(1/fps, 3),
    ):
        self.address = address
        self.port = port
        self.fps = fps
        self.maps_path = maps
        self.text = text
        self.s = None
        self.screen = None
        self.font = None
        self.wait_fps = round(1/fps, 3)

        self.objective_x = -1
        self.objective_y = -1
        self.allied_base = None
        self.axis_base = None
        self.graph = {}
        self.agents = {}
        self.dins = {}
        self.factor = 2

        self.iteration = 0

        self.tile_size = 24
        self.horizontal_tiles = 32
        self.vertical_tiles = 32

        self.map_width = self.tile_size * self.horizontal_tiles
        self.map_height = self.tile_size * self.vertical_tiles

        self.xdesp = 0
        self.ydesp = 0
        self.size = [self.map_width, self.map_height]

        self.show_help = False
        self.show_fovs = True
        self.show_info = True
        self.quit = False

        self.fps = list()

        this_dir, _ = os.path.split(__file__)
        parent_dir = os.path.abspath(os.path.join(this_dir, os.pardir))
        self.assets_path = f"{parent_dir}{os.sep}assets{os.sep}"
        self.allied_base_sprite = pygame.image.load(
            os.path.join(self.assets_path, "base4.png")
        )
        self.axis_base_sprite = pygame.image.load(
            os.path.join(self.assets_path, "base3.png")
        )
        self.wall_sprite = pygame.image.load(
            os.path.join(self.assets_path, "wall2.png")
        )
        self.terrain_sprites = cycle([
            pygame.image.load(os.path.join(self.assets_path, "terrain.jpg")),
            pygame.image.load(os.path.join(self.assets_path, "grass2.jpg")),
            pygame.image.load(os.path.join(self.assets_path, "grass.jpg"))]
        )
        self.terrain_sprite = next(self.terrain_sprites)

        self.pack_images = {
            PACK_MEDICPACK: pygame.image.load(os.path.join(self.assets_path, "medpack2.png")),
            PACK_AMMOPACK: pygame.image.load(os.path.join(self.assets_path, "ammopack.png"))
        }

        self.sprites = {}
        self.graves = {}
        self.flag_sprite = None

        self.replay = replay
        self.dump = dump
        self.log = log
        self.file = None
        self.game_log = []
        self.wait_fps = wait_fps

    def main(self):
        if self.text:
            # curses.wrapper(self._main)
            self._main()
        else:
            self._main()

    def read_msg(self):
        if not self.replay:
            try:
                size_of_msg = self.s.recv(4)
            except socket.timeout:
                size_of_msg = 0
            if not size_of_msg:
                return None
            size_of_msg = struct.unpack(">I", size_of_msg)[0]

            data = bytes()
            while len(data) < size_of_msg:
                packet = self.s.recv(size_of_msg - len(data))
                if not packet:
                    break
                data += packet

            if len(data) == 0:
                data = None
            data = msgpack.unpackb(data, raw=False, strict_map_key=False)
            return data
        else:
            if len(self.game_log) > 0:
                data = self.game_log.pop(0)
                if data:
                    data = json.loads(data)
                    data = self._load_json(data)
                    return data
            return {Msg.TYPE: TCP.COM, Msg.BODY: Msg.QUIT}

    def _load_json(self, data):
        if isinstance(data, dict):
            new_data = dict()
            for key, value in data.items():
                new_data[int(key)] = self._load_json(value)
        elif isinstance(data, list):
            new_data = list()
            for element in data:
                new_data.append(self._load_json(element))
        else:
            new_data = data
        return new_data

    def _main(self, stdscr=None):
        error = False
        if not self.dump:
            if not self.text:
                # Init pygame
                pygame.init()
                self.font = pygame.font.SysFont("ttf-font-awesome", 16)
                self.help_font = pygame.font.SysFont("ttf-font-awesome", 42)

                # Set the height and width of the self.screen
                self.screen = pygame.display.set_mode(self.size)

            else:
                stdscr = curses.initscr()
                curses.start_color()
                curses.noecho()
                curses.cbreak()
                stdscr.keypad(1)

        else:
            logger.success(f"Dumping log to {self.log}")
            self.file = open(self.log, "w")

        try:
            if self.replay:
                logger.success(f"Loading log from {self.log}")
                with open(self.log, "r") as rfile:
                    self.game_log = rfile.read()
                self.game_log = self.game_log.split("\nSEP\n")
            else:
                # Init socket
                self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if self.s:
                    self.s.settimeout(0.1)
                    self.s.connect((self.address, self.port))

            while not self.quit:
                start_time = time.time()
                if not self.dump:
                    self.draw(stdscr)
                if self.replay:
                    time.sleep(self.wait_fps)

                data = self.read_msg()

                if data is None:
                    continue

                if data[int(Msg.TYPE)] == TCP.COM:
                    if data[int(Msg.BODY)] == Msg.WELCOME:
                        if not self.replay:
                            msg_to_send = msgpack.packb(
                                {Msg.TYPE: TCP.COM, Msg.BODY: Msg.READY},
                                use_bin_type=True,
                            )
                            size_of_package = len(msg_to_send)
                            msg = struct.pack(">I", size_of_package) + msg_to_send
                            self.s.send(msg)
                    elif data[Msg.BODY] == Msg.ACCEPT:
                        pass
                    elif data[Msg.BODY] == Msg.QUIT:
                        self.quit = True

                elif data[Msg.TYPE] == TCP.MAP:
                    if self.dump:
                        self.dump_data(data)
                    else:
                        mapname = data[Msg.BODY]
                        result = self.load_map(mapname)
                        if result["status"] != "ok":
                            error = result["value"]
                            self.quit = True

                        if not self.text:
                            self.init_sprites()

                elif data[Msg.TYPE] == TCP.AGL:
                    if self.dump:
                        self.dump_data(data)
                    else:
                        self.agl_parse(data[Msg.BODY])
                        self.fps.append(1 / (time.time() - start_time))

                elif data[Msg.TYPE] == TCP.TIME:
                    pass
                elif data[Msg.TYPE] == TCP.ERR:
                    pass
                else:
                    # Unknown message type
                    pass

        except Exception as e:
            tb = traceback.format_exc()
            error = str(e) + "\n" + tb
            if self.text:
                curses.nocbreak()
                # self.stdscr.keypad(False)
                curses.echo()
                curses.endwin()
            logger.exception("Exception.")

        finally:
            if not self.replay:
                logger.info("Sending QUIT message...")
                msg_to_send = msgpack.packb(
                    {Msg.TYPE: TCP.COM, Msg.BODY: Msg.QUIT}, use_bin_type=True,
                )
                size_of_package = len(msg_to_send)
                msg = struct.pack(">I", size_of_package) + msg_to_send
                self.s.send(msg)

                logger.info("Closing...")
                # Close socket
                self.s.close()

            if not self.dump:
                if not self.text:
                    pygame.quit()
                else:
                    curses.nocbreak()
                    # self.stdscr.keypad(False)
                    curses.echo()
                    curses.endwin()
            else:
                logger.info("Closing...")
                self.file.close()
            if error:
                logger.error(str(error))

    def dump_data(self, data):
        self.file.write(json.dumps(data))
        self.file.write("\nSEP\n")

    def agl_parse(self, data):
        self.dins = {}

        for agent in data[Msg.AGENTS]:
            self.agents[agent[Msg.CONTENT_NAME]] = agent

        for pack in data[Msg.PACKS]:
            self.dins[pack[Msg.CONTENT_NAME]] = pack

    def draw(self, stdscr):
        if self.text:
            self.textdraw(stdscr)
        else:
            self.pygamedraw()

    def pygamedraw(self):
        global draw_rect

        events = pygame.event.get()
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_LEFT:
                    self.xdesp += self.tile_size
                elif event.key == pygame.K_RIGHT:
                    self.xdesp -= self.tile_size
                elif event.key == pygame.K_DOWN:
                    self.ydesp -= self.tile_size
                elif event.key == pygame.K_UP:
                    self.ydesp += self.tile_size
                elif event.key == pygame.K_x:
                    self.tile_size += 2
                elif event.key == pygame.K_z:
                    self.tile_size -= 2
                elif event.key == pygame.K_f:
                    self.show_fovs = not self.show_fovs
                elif event.key == pygame.K_i:
                    self.show_info = not self.show_info
                elif event.key == pygame.K_b:
                    self.terrain_sprite = next(self.terrain_sprites)
                elif event.key == pygame.K_r:
                    draw_rect = not draw_rect
                elif event.key == pygame.K_h:
                    self.show_help = not self.show_help
                elif event.key == pygame.K_ESCAPE:
                    self.quit = True
            elif event.type == pygame.QUIT:
                self.quit = True

        # Clear screen
        self.pygame_draw_background()

        # Draw bases
        self.pygame_draw_bases()

        # Draw Map
        self.pygame_draw_walls()

        # Draw FPS
        self.pygame_draw_fps()

        # Draw items
        self.pygame_draw_packs()

        # Draw units
        self.pygame_draw_units()

        # Show help
        self.pygame_draw_help()

        pygame.display.update()  # flip()
        self.iteration += 1

    def pygame_draw_units(self):
        for name, agent in self.agents.items():
            health = float(agent[Msg.CONTENT_HEALTH])
            posx = (
                    int(float(agent[Msg.CONTENT_POSITION][0]) * self.tile_size / 8.0)
                    + self.xdesp
            )
            posy = (
                    int(float(agent[Msg.CONTENT_POSITION][2]) * self.tile_size / 8.0)
                    + self.ydesp
            )

            if float(health) > 0:
                carrying = agent[Msg.CONTENT_CARRYINGFLAG]

                # agent_type = {0: "X", 1: "*", 2: "+", 3: "Y", 4: "^"}.get(
                agent_type = {CLASS_NONE: "soldier", CLASS_SOLDIER: "soldier", CLASS_MEDIC: "medic", CLASS_ENGINEER: "engineer",
                              CLASS_FIELDOPS: "fieldops"}.get(agent[Msg.CONTENT_TYPE], "soldier")

                team = {TEAM_ALLIED: (255, 50, 50), TEAM_AXIS: (100, 100, 255)}.get(
                    agent[Msg.CONTENT_TEAM], (255, 255, 0)
                )

                team_aplha = {TEAM_ALLIED: (255, 100, 100, 100), TEAM_AXIS: (100, 100, 255, 100)}.get(
                    agent[Msg.CONTENT_TEAM], (255, 255, 0, 255)
                )

                ammo = float(agent[Msg.CONTENT_AMMO])

                # print avatar
                if name not in self.sprites:
                    sprite = MySprite(name=agent_type, team=agent[Msg.CONTENT_TEAM], num_sprites=8, scale=0.55)
                    self.sprites[name] = sprite
                angx = float(agent[Msg.CONTENT_HEADING][0])
                angy = float(agent[Msg.CONTENT_HEADING][2])
                self.sprites[name].update(posx, posy, angx, angy)
                self.sprites[name].draw(self.screen)

                if self.show_info:
                    # print name
                    text = self.font.render(agent[Msg.CONTENT_NAME], True, (255, 255, 255))
                    self.screen.blit(
                        text,
                        (
                            posx - text.get_width() // 2 + 25,
                            posy - text.get_height() // 2 - 25,
                        ),
                    )
                    rect = self.sprites[name].rect
                    health_bar = Rect(rect.bottomleft[0], rect.bottomleft[1], rect.width, 4)
                    pygame.draw.rect(self.screen, (255, 0, 0), health_bar)
                    health_bar = Rect(rect.bottomleft[0], rect.bottomleft[1], min(100, health * rect.width / 100), 4)
                    pygame.draw.rect(self.screen, (0, 255, 0), health_bar)

                    ammo_bar = Rect(rect.bottomleft[0], rect.bottomleft[1] + 5, rect.width, 4)
                    pygame.draw.rect(self.screen, (255, 255, 255), ammo_bar)
                    ammo_bar = Rect(rect.bottomleft[0], rect.bottomleft[1] + 5, min(100, ammo * rect.width / 100), 4)
                    pygame.draw.rect(self.screen, (106, 115, 120), ammo_bar)

                # is carring flag?
                if carrying:
                    flagx, flagy = self.sprites[name].rect.topright
                    self.flag_sprite.update(flagx, flagy, 0, -1, force_animation=True)
                    self.flag_sprite.draw(self.screen)

                # print fov
                if self.show_fovs:
                    # compute direction
                    angx = float(agent[Msg.CONTENT_HEADING][0])
                    angy = float(agent[Msg.CONTENT_HEADING][2])

                    angle = get_angle(angx, angy)

                    for j in range(0, int(48 * (self.tile_size / 8)), 1):
                        pygame.gfxdraw.arc(
                            self.screen,
                            posx,
                            posy,
                            j,
                            int(-45 + angle),
                            int(45 + angle),
                            team_aplha,
                        )

            else:
                team = agent[Msg.CONTENT_TEAM]
                if team not in self.graves:
                    sprite = MySprite(name="grave", team=team, num_sprites=1, scale=0.3)
                    self.graves[team] = sprite
                self.graves[team].update(posx, posy, 0, -1)
                self.graves[team].draw(self.screen)

    def pygame_draw_packs(self):
        for pack in self.dins.values():
            posx = int(
                pack[Msg.CONTENT_POSITION][0] * (self.tile_size / 8.0) + self.xdesp
            )
            posy = int(
                pack[Msg.CONTENT_POSITION][2] * (self.tile_size / 8.0) + self.ydesp
            )

            item_type = pack[Msg.CONTENT_TYPE]  # {1001: "M", 1002: "A", 1003: "F"}.get(
            # pack[Msg.CONTENT_TYPE], "X"
            # )

            if item_type != PACK_OBJPACK:

                '''color = {
                    1001: (88, 214, 141),  # (255, 255, 255),
                    1002: (155, 89, 182),  # (255, 255, 255),
                    1003: (255, 255, 0),
                }.get(pack[Msg.CONTENT_TYPE], "X")

                pygame.draw.circle(self.screen, color, [posx, posy], 6)
                text = self.font.render(item_type, True, (0, 0, 0))
                self.screen.blit(
                    text, (posx - text.get_width() // 2, posy - text.get_height() // 2)
                )'''
                self.screen.blit(
                    self.pack_images[item_type],
                    (
                        posx, posy
                    ),
                )
            else:
                self.flag_sprite.update(posx, posy, 0, -1, force_animation=True)
                self.flag_sprite.draw(self.screen)

    def pygame_draw_fps(self):
        if len(self.fps) > 5:
            fps = int(sum(self.fps[-5:]) / 5)
            text = self.font.render(str(fps) + " FPS", True, (255, 255, 255))
            self.screen.blit(text, (1, 1))

    def pygame_draw_walls(self):
        color_wall = (100, 100, 100)
        for y in range(0, len(list(self.graph.items()))):
            for x in range(0, 32):
                try:
                    if list(self.graph.items())[y][1][x] == "*":
                        """pygame.draw.rect(
                            self.screen,
                            color_wall,
                            (
                                x * self.tile_size + self.xdesp,
                                y * self.tile_size + self.ydesp,
                                self.tile_size,
                                self.tile_size,
                            ),
                        )"""
                        self.screen.blit(
                            self.wall_sprite,
                            (
                                x * self.tile_size + self.xdesp,
                                y * self.tile_size + self.ydesp,
                            ),
                        )
                except:
                    pass

    def pygame_draw_bases(self):
        if self.allied_base is not None:
            if len(self.allied_base) == 5:
                draw = bool(int(self.allied_base[4]))
            else:
                draw = True
            if draw:
                color = (255, 0, 0)
                xpos = int(self.allied_base[0]) * self.tile_size + self.xdesp
                ypos = int(self.allied_base[1]) * self.tile_size + self.ydesp
                xwidth = (
                        int(self.allied_base[2]) * self.tile_size
                        - xpos
                        + self.tile_size
                        + self.xdesp
                )
                ywidth = (
                        int(self.allied_base[3]) * self.tile_size
                        - ypos
                        + self.tile_size
                        + self.ydesp
                )

                self.screen.blit(self.allied_base_sprite, (xpos, ypos))
        if self.axis_base is not None:
            if len(self.axis_base) == 5:
                draw = bool(int(self.axis_base[4]))
            else:
                draw = True
            if draw:
                color = (0, 0, 255)
                xpos = int(self.axis_base[0]) * self.tile_size + self.xdesp
                ypos = int(self.axis_base[1]) * self.tile_size + self.ydesp
                xwidth = (
                        int(self.axis_base[2]) * self.tile_size
                        - xpos
                        + self.tile_size
                        + self.xdesp
                )
                ywidth = (
                        int(self.axis_base[3]) * self.tile_size
                        - ypos
                        + self.tile_size
                        + self.ydesp
                )

                self.screen.blit(self.axis_base_sprite, (xpos, ypos))

    def pygame_draw_background(self):
        color_background = (189, 236, 182)  # (245, 245, 220)
        # pygame.draw.rect(
        #    self.screen, color_background, (0, 0, self.map_width, self.map_height)
        # )
        self.screen.blit(self.terrain_sprite, (0, 0))

    def textdraw(self, stdscr):
        height, width = stdscr.getmaxyx()

        # Draw Map
        for name, v in list(self.graph.items()):
            try:
                newline = ""
                for char in v:
                    newline += char * self.factor
                if height > name:
                    stdscr.addstr(name, 0, str(newline))
            except:
                pass

        # Draw bases
        # ALLIED BASE
        if self.allied_base is not None:
            curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_RED)  # ALLIED BASE
            for y in range(int(self.allied_base[1]), int(self.allied_base[3])):
                for x in range(
                        int(self.allied_base[0]) * self.factor,
                        int(self.allied_base[2]) * self.factor,
                ):
                    if height > y:
                        stdscr.addstr(y, x, " ", curses.color_pair(4))

        # AXIS BASE
        if self.axis_base is not None:
            curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLUE)  # AXIS BASE
            for y in range(int(self.axis_base[1]), int(self.axis_base[3])):
                for x in range(
                        int(self.axis_base[0]) * self.factor,
                        int(self.axis_base[2]) * self.factor,
                ):
                    if height > y:
                        stdscr.addstr(y, x, " ", curses.color_pair(3))

        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        # PACKS
        # for k, v in list(self.dins.items()):
        for pack in self.dins.values():
            #  Type
            symbol = {"1001": "M", "1002": "A", "1003": "F"}.get(
                str(pack[Msg.CONTENT_TYPE]), "X"
            )

            y = int(float(pack[Msg.CONTENT_POSITION][2]) / 8)
            x = int(float(pack[Msg.CONTENT_POSITION][0]) / (8 / self.factor))
            if height > y:
                stdscr.addstr(y, x, symbol, curses.color_pair(2))

        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_RED)  # ALLIED
        curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)  # AXIS
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)  #  OTHER / DEAD

        # AGENTS
        stats_allied = []  # ""
        stats_axis = []  # ""
        # for k, v in list(self.agents.items()):
        for agent in self.agents.values():
            name = agent[Msg.CONTENT_NAME]
            name = name[:5] + ".." + name[-5:] if len(name) > 12 else name
            # Type
            symbol = {1: "*", 2: "+", 3: "Y", 4: "^"}.get(agent[Msg.CONTENT_TYPE], "X")

            # Team (or Carrier)
            team_color = {100: 5, 200: 6, }.get(agent[Msg.CONTENT_TEAM], 1)

            if agent[Msg.CONTENT_CARRYINGFLAG]:
                team_color = 2

            # Draw in map
            y = int(float(agent[Msg.CONTENT_POSITION][2]) / 8)
            x = int(float(agent[Msg.CONTENT_POSITION][0]) / (8 / self.factor))
            health = int(agent[Msg.CONTENT_HEALTH])
            ammo = int(agent[Msg.CONTENT_AMMO])
            if health > 0:
                if height > y:
                    stdscr.addstr(y, x, symbol, curses.color_pair(team_color))  #  Alive
            else:
                if height > y:
                    stdscr.addstr(y, x, "D", curses.color_pair(7))  #  Dead
            # Write stats
            if agent[Msg.CONTENT_TEAM] == 100:
                if health > 0:
                    stats_allied.append(
                        f" | {symbol} {name.ljust(4)} {health:03d} {ammo:03d} "
                    )
                else:
                    stats_allied.append(f" | {symbol} {name.ljust(4)} --- --- ")
            elif agent[Msg.CONTENT_TEAM] == 200:
                if health > 0:
                    # stats_axis += " | %s %s %03d %03d " % (c, k, int(v["health"]), int(v["ammo"]))
                    stats_axis.append(
                        f" | {symbol} {name.ljust(4)} {health:03d} {ammo:03d} "
                    )
                else:
                    stats_axis.append(f" | {symbol} {name.ljust(4)} --- --- ")

        row = 33
        for _agents in chunks(stats_allied, 4):
            line = "".join(_agents)
            if height > row:
                stdscr.addstr(row, 1, str(line), curses.color_pair(5))
            row += 1
        # stdscr.addstr(34, 1, blank)
        for _agents in chunks(stats_axis, 4):
            line = "".join(_agents)
            if height > row:
                stdscr.addstr(row, 1, str(line), curses.color_pair(6))
            row += 1

        # Draw FPS
        if len(self.fps) > 5:
            fps = int(sum(self.fps[-5:]) / 5)
            if height > row:
                stdscr.addstr(row, 1, "{:03d} FPS".format(fps), curses.color_pair(7))
            row += 1

        # Refresh screen
        try:
            stdscr.refresh()
        except:
            pass

    def load_map(self, map_name):
        try:
            if self.maps_path is not None:
                path = f"{self.maps_path}{os.sep}{map_name}{os.sep}"
            else:
                this_dir, _ = os.path.split(__file__)
                parent_dir = os.path.abspath(os.path.join(this_dir, os.pardir))
                path = f"{parent_dir}{os.sep}maps{os.sep}{map_name}{os.sep}"

            if os.path.exists(f"{path}{map_name}.json"):
                with open(f"{path}{map_name}.json") as f:
                    mapf = json.load(f)
                    self.objective_x = int(mapf["objective"][0])
                    self.objective_y = int(mapf["objective"][1])
                    self.allied_base = mapf["spawn"]["allied"]
                    self.axis_base = mapf["spawn"]["axis"]
                    cost = open(f"{path}{mapf['cost_map']['file']}", "r")

            else:
                mapf = open(f"{path}{map_name}.txt", "r")
                cost = open(f"{path}{map_name}_cost.txt", "r")
                for line in mapf.readlines():
                    if "pGomas_OBJECTIVE" in line:
                        splitted_line = line.split()
                        self.objective_x = copy.copy(int(splitted_line[1]))
                        self.objective_y = copy.copy(int(splitted_line[2]))
                    elif "pGomas_SPAWN_ALLIED" in line:
                        splitted_line = line.split()
                        splitted_line.pop(0)
                        self.allied_base = copy.copy(splitted_line)
                    elif "pGomas_SPAWN_AXIS" in line:
                        splitted_line = line.split()
                        splitted_line.pop(0)
                        self.axis_base = copy.copy(splitted_line)
                mapf.close()

            y = 0
            for line in cost.readlines():
                self.graph[y] = line.strip("\r\n")
                y += 1
            cost.close()
            if not self.text:
                logger.info("Map loaded.")
            return {"status": "ok"}
        except Exception as e:
            tb = traceback.extract_stack()
            return {
                "status": "error",
                "value": str(e) + "\n" + "\n".join([repr(i) for i in tb]),
            }

    def init_sprites(self):
        xpos = int(self.allied_base[0]) * self.tile_size + self.xdesp
        ypos = int(self.allied_base[1]) * self.tile_size + self.ydesp
        xwidth = (
                int(self.allied_base[2]) * self.tile_size
                - xpos
                + self.tile_size
                + self.xdesp
        )
        ywidth = (
                int(self.allied_base[3]) * self.tile_size
                - ypos
                + self.tile_size
                + self.ydesp
        )

        self.allied_base_sprite.convert()
        self.allied_base_sprite = pygame.transform.scale(
            self.allied_base_sprite, (xwidth, ywidth)
        )

        xpos = int(self.axis_base[0]) * self.tile_size + self.xdesp
        ypos = int(self.axis_base[1]) * self.tile_size + self.ydesp
        xwidth = (
                int(self.axis_base[2]) * self.tile_size - xpos + self.tile_size + self.xdesp
        )
        ywidth = (
                int(self.axis_base[3]) * self.tile_size - ypos + self.tile_size + self.ydesp
        )

        self.axis_base_sprite.convert()
        self.axis_base_sprite = pygame.transform.scale(
            self.axis_base_sprite, (xwidth, ywidth)
        )

        self.wall_sprite.convert()
        self.wall_sprite = pygame.transform.scale(
            self.wall_sprite, (self.tile_size, self.tile_size)
        )

        self.terrain_sprite.convert()
        self.terrain_sprite = pygame.transform.scale(
            self.terrain_sprite, (self.map_width, self.map_height)
        )

        self.flag_sprite = MySprite(name="flag", team=TEAM_NONE, num_sprites=8, scale=0.1, fr=4)

        scale = 0.15
        self.pack_images = {k: pygame.transform.scale(img, (int(img.get_size()[0] * scale), int(img.get_size()[1] * scale))) for
                            k, img in self.pack_images.items()}

    def pygame_draw_help(self):
        if self.show_help:
            text = self.help_font.render("Show/Hide Field of View: F", True, (255, 255, 255))
            self.screen.blit(text, (150, 70), )

            text = self.help_font.render("Show/Hide Info (Bars and names): I", True, (255, 255, 255))
            self.screen.blit(text, (150, 100), )

            text = self.help_font.render("Change background : B", True, (255, 255, 255))
            self.screen.blit(text, (150, 130), )

            text = self.help_font.render("Show/Hide Bounding Boxes: R", True, (255, 255, 255))
            self.screen.blit(text, (150, 160), )

            text = self.help_font.render("Move camera: Arrows", True, (255, 255, 255))
            self.screen.blit(text, (150, 190), )

            text = self.help_font.render("Zoom In/Out: X,Z", True, (255, 255, 255))
            self.screen.blit(text, (150, 220), )

            text = self.help_font.render("Quit: ESCAPE", True, (255, 255, 255))
            self.screen.blit(text, (150, 250), )


class MySprite(pygame.sprite.Sprite):
    def __init__(self, name: str, team: int, num_sprites: int, folder: str = "assets", scale: float = 1.0, fr=1):
        super(MySprite, self).__init__()
        # adding all the images to sprite array
        this_dir, _ = os.path.split(__file__)
        this_dir = os.path.abspath(os.path.join(this_dir, os.pardir))

        team = {TEAM_ALLIED: "allied", TEAM_AXIS: "axis", TEAM_NONE: ""}.get(team)
        self.images = [pygame.image.load(f'{this_dir}{os.sep}{folder}{os.sep}{name}_{team}{i}.png') for i in
                       range(1, num_sprites + 1)]
        self.images = [pygame.transform.scale(img, (int(img.get_size()[0] * scale), int(img.get_size()[1] * scale)))
                       for img in self.images]
        self.images = [pygame.transform.rotate(img, -90) for img in self.images]
        self.original_images = [copy.copy(img) for img in self.images]

        # index value to get the image from the array
        # initially it is 0
        self.index = 0

        # now the image that we will display will be the index from the image array
        self.image = self.images[self.index]
        self.x = 0
        self.y = 0

        self.rect = self.image.get_rect(center=(self.x, self.y))
        self.fr = cycle(range(fr))

    def update(self, x, y, angx, angy, force_animation=False):

        fr = next(self.fr)
        if fr == 0:
            if self.x != x or self.y != y or force_animation:
                # when the update method is called, we will increment the index
                self.index += 1

                # if the index is larger than the total images
                if self.index >= len(self.images):
                    # we will make the index to 0 again
                    self.index = 0

        self.x, self.y = x, y

        angle = get_angle(angx, angy)

        self.image = pygame.transform.rotate(self.original_images[self.index], -angle)
        self.rect = self.image.get_rect(center=(self.x, self.y))

    def draw(self, surface):
        if draw_rect:
            pygame.draw.rect(surface, (255, 0, 0), self.rect, 1)
        surface.blit(self.image, self.rect)


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
    parser.add_argument(
        "--fps", default=30, help="Set desired FPS rate"
    )
    parser.add_argument("--text", default=False, help="Use text render")

    parser.add_argument("--log", default="match.log", help="File to save the game")

    args = parser.parse_args()
    render = Render(args.ip, args.port, args.maps, args.fps, args.text)
    render.main()
    sys.exit(0)
