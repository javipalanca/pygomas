#!/usr/bin/env python
# -*- coding: UTF8 -*-
import argparse
import copy
import curses
import os
import socket
import sys

stdscr = None
allied_base = None
axis_base = None
graph = {}
pad = None
f = None
agents = {}
dins = {}
factor = 2
curses_up = False
maps_path = None


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i : i + n]


def agl_parse(data):
    global allied_base
    global axis_base
    global agents
    global dins

    f.write("\nAGL_PARSE\n")
    agl = data.split()
    nagents = int(agl[1])
    agl = agl[2:]
    separator = nagents * 15
    f.write("NAGENTS = %s\n" % (str(nagents)))
    agent_data = agl[:separator]
    din_data = agl[separator:]
    f.write("AGENT_DATA: {}\n".format(agent_data))
    for i in range(nagents):
        agents[agent_data[0]] = {
            "type": agent_data[1],
            "team": agent_data[2],
            "health": agent_data[3],
            "ammo": agent_data[4],
            "carrying": agent_data[5],
            "posx": int(float(agent_data[6].strip("(,)"))),
            "posy": int(float(agent_data[7].strip("(,)"))),
            "posz": int(float(agent_data[8].strip("(,)"))),
        }
        f.write("AGENT {}\n".format(agents[agent_data[0]]))
        agent_data = agent_data[15:]

    f.write("DIN_DATA: {}\n".format(din_data))
    ndin = int(din_data[0]) if din_data else 0
    f.write("NDIN = %s\n" % (str(ndin)))
    din_data = din_data[1:]
    dins = {}
    for din in range(ndin):
        dins[din_data[0]] = {
            "type": din_data[1],
            "posx": int(float(din_data[2].strip("(,)"))),
            "posy": int(float(din_data[3].strip("(,)"))),
            "posz": int(float(din_data[4].strip("(,)"))),
        }
        f.write("DIN {}\n".format(dins[din_data[0]]))
        din_data = din_data[5:]


def draw():
    global agents
    global factor

    f.write("DRAW\n")
    # Draw Map
    for k, v in list(graph.items()):
        f.write("DRAW {}\n".format(k))
        try:
            newline = ""
            for char in v:
                newline += char * factor
            stdscr.addstr(k, 0, str(newline))
        except:
            pass

    # Draw bases
    try:
        # ALLIED BASE
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_RED)  # ALLIED BASE
        for y in range(int(allied_base[1]), int(allied_base[3])):
            for x in range(int(allied_base[0]) * factor, int(allied_base[2]) * factor):
                f.write("BASE " + str(y) + " " + str(x) + "; \n")
                stdscr.addstr(y, x, " ", curses.color_pair(4))
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLUE)  # AXIS BASE

        # AXIS BASE
        for y in range(int(axis_base[1]), int(axis_base[3])):
            for x in range(int(axis_base[0]) * factor, int(axis_base[2]) * factor):
                f.write("BASE " + str(y) + " " + str(x) + "; \n")
                stdscr.addstr(y, x, " ", curses.color_pair(3))

        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        # PACKS
        for k, v in list(dins.items()):
            #  Type
            if v["type"] == "1001":
                c = "M"
            elif v["type"] == "1002":
                c = "A"
            elif v["type"] == "1003":
                c = "F"
            else:
                c = "X"
            y = int(float(v["posz"]) / 8)
            x = int(float(v["posx"]) / (8 / factor))
            stdscr.addstr(y, x, c, curses.color_pair(2))

        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_RED)  # ALLIED
        curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)  # AXIS
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)  #  OTHER / DEAD

        # AGENTS
        stats_allied = []  # ""
        stats_axis = []  # ""
        for k, v in list(agents.items()):
            # Type
            if v["type"] == "0":
                c = "X"
            elif v["type"] == "1":
                c = "*"
            elif v["type"] == "2":
                c = "+"
            elif v["type"] == "3":
                c = "Y"
            elif v["type"] == "4":
                c = "^"
            else:
                c = "X"
            # Team (or Carrier)
            if v["carrying"] == "1":
                t = 2
            elif v["team"] == "100":
                t = 5
            elif v["team"] == "200":
                t = 6
            else:
                t = 1
            # Draw in map
            y = int(float(v["posz"]) / 8)
            x = int(float(v["posx"]) / (8 / factor))
            if int(v["health"]) > 0:
                stdscr.addstr(y, x, c, curses.color_pair(t))  #  Alive
            else:
                stdscr.addstr(y, x, "D", curses.color_pair(7))  #  Dead
            # Write stats
            if v["team"] == "100":
                if int(v["health"]) > 0:
                    # stats_allied += " | %s %s %03d %03d " % (c, k, int(v["health"]), int(v["ammo"]))
                    stats_allied.append(
                        f" | {c} {k.ljust(4)} {int(v['health']):03d} {int(v['ammo']):03d} "
                    )
                else:
                    # stats_allied += " | %s %s --- --- " % (c, k)
                    stats_allied.append(f" | {c} {k.ljust(4)} --- --- ")
            elif v["team"] == "200":
                if int(v["health"]) > 0:
                    # stats_axis += " | %s %s %03d %03d " % (c, k, int(v["health"]), int(v["ammo"]))
                    stats_axis.append(
                        f" | {c} {k.ljust(4)} {int(v['health']):03d} {int(v['ammo']):03d} "
                    )
                else:
                    # stats_axis += " | %s %s --- --- " % (c, k)
                    stats_axis.append(f" | {c} {k.ljust(4)} --- --- ")
        blank = " " * 81
        # stdscr.addstr(33, 1, blank)
        row = 33
        for _agents in chunks(stats_allied, 4):
            line = "".join(_agents)
            stdscr.addstr(row, 1, str(line), curses.color_pair(5))
            row += 1
        # stdscr.addstr(34, 1, blank)
        for _agents in chunks(stats_axis, 4):
            line = "".join(_agents)
            stdscr.addstr(row, 1, str(line), curses.color_pair(6))
            row += 1
    except Exception as exc:
        f.write("\nEXCEPTION IN DRAW: " + str(exc) + "\n")

    # Refresh screen
    try:
        stdscr.refresh()
    except:
        pass


def load_map(map_name):
    global allied_base
    global axis_base
    global maps_path

    if maps_path is not None:
        path = f"{maps_path}{os.sep}{map_name}{os.sep}{map_name}"
    else:
        this_dir, _ = os.path.split(__file__)
        path = f"{this_dir}{os.sep}maps{os.sep}{map_name}{os.sep}{map_name}"

    mapf = open(f"{path}.txt", "r")
    cost = open(f"{path}_cost.txt", "r")

    for line in mapf.readlines():
        if "pGomas_SPAWN_ALLIED" in line:
            line = line.split()
            line.pop(0)
            allied_base = copy.copy(line)
            f.write("\n ALLIED_BASE: {}\n".format(line))
        elif "pGomas_SPAWN_AXIS" in line:
            line = line.split()
            line.pop(0)
            axis_base = copy.copy(line)
            f.write("\n AXIS_BASE: {}\n".format(line))
    mapf.close()
    f.write("MAPF LOADED\n")

    y = 0
    for line in cost.readlines():
        graph[y] = line.strip("\r\n")
        y += 1
    cost.close()
    # print "GRAPH",str(graph)
    f.write(str(graph))


def quit():
    global curses_up
    if curses_up:
        # Terminate curses
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.endwin()
        curses_up = False


def main(address="localhost", port=8001, maps=None):
    # Main
    global f
    global maps_path
    global stdscr
    global curses_up

    maps_path = maps

    f = open("/tmp/tv.log", "w")
    f.write("LOG\n")

    # Init curses
    stdscr = curses.initscr()
    curses.start_color()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(1)
    # curses.curs_set(0)
    curses_up = True
    # stdscr.addstr("CURSES OPEN\n")
    # stdscr.refresh()
    # pad = curses.newpad(32,32)

    try:
        # Init socket
        f.write(f"ADDRESS: {address}\n")
        f.write(f"PORT: {port}\n")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if s:
            s.connect((address, port))
            rfile = s.makefile("rb", -1)
            wfile = s.makefile("wb", 0)
            f.write("SOCKET OPEN %s\n" % (str(s)))
            data = rfile.readline()
            f.write("Server sent: %s\n" % (data))
            wfile.write(bytes("READY\n", encoding="UTF-8"))
            loop = True
            while loop:
                data = ""
                data = rfile.readline()
                data = str(data)
                f.write("Server sent: %s\n" % (data))
                if "COM" in data[0:5]:
                    if "Accepted" in data:
                        pass
                    elif "Closed" in data:
                        loop = False
                elif "MAP" in data[0:5]:
                    f.write("MAP MESSAGE: %s\n" % (data))
                    p = data.split()
                    mapname = p[2]
                    f.write("MAPNAME: %s\n" % (mapname))
                    load_map(mapname)
                elif "AGL" in data[0:5]:
                    f.write("\nAGL\n")
                    agl_parse(data)
                elif "TIM" in data[0:5]:
                    pass
                elif "ERR" in data[0:5]:
                    pass
                else:
                    # Unknown message type
                    pass
                draw()

            # Close socket
            del rfile
            del wfile
            s.send(bytes("QUIT\n", encoding="UTF-8"))
            s.close()

    except Exception as e:
        # Terminate
        if s:
            s.send(bytes("QUIT\n", encoding="UTF-8"))
            s.close()

        f.write("Exception: {}\n".format(e))
        quit()

    quit()

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
