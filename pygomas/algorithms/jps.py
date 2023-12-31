import heapq
import math
import time

import numpy as np
from loguru import logger

OBSTACLE = 0
MANHATTAN = 1
EUCLIDEAN = 2


class JPSAlgorithm(object):
    """Jump-Point-Search algorithm"""

    def __init__(self, map_array, downsample=False):
        self.array = map_array
        self.downsample = downsample
        if downsample:
            m, n = self.array.shape
            self.array = self.array.reshape(m // 8, 8, n // 8, 8).min(axis=(1, 3))

    @staticmethod
    def heuristic(a, b, hchoice=EUCLIDEAN):
        if hchoice == MANHATTAN:
            xdist = math.fabs(b[0] - a[0])
            ydist = math.fabs(b[1] - a[1])
            if xdist > ydist:
                return 14 * ydist + 10 * (xdist - ydist)
            else:
                return 14 * xdist + 10 * (ydist - xdist)
        if hchoice == EUCLIDEAN:
            return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)

    def blocked(self, cx, cy, dx, dy):
        if cx + dx < 0 or cx + dx >= self.array.shape[0]:
            return True
        if cy + dy < 0 or cy + dy >= self.array.shape[1]:
            return True
        if dx != 0 and dy != 0:
            if (
                self.array[cx + dx][cy] == OBSTACLE
                and self.array[cx][cy + dy] == OBSTACLE
            ):
                return True
            if self.array[cx + dx][cy + dy] == OBSTACLE:
                return True
        else:
            if dx != 0:
                if self.array[cx + dx][cy] == OBSTACLE:
                    return True
            else:
                if self.array[cx][cy + dy] == OBSTACLE:
                    return True
        return False

    def dblock(self, cx, cy, dx, dy):
        if self.array[cx - dx][cy] == OBSTACLE and self.array[cx][cy - dy] == OBSTACLE:
            return True
        else:
            return False

    @staticmethod
    def direction(cx, cy, px, py):
        dx = int(math.copysign(1, cx - px))
        dy = int(math.copysign(1, cy - py))
        if cx - px == 0:
            dx = 0
        if cy - py == 0:
            dy = 0
        return dx, dy

    def node_neighbours(self, cx, cy, parent):
        neighbours = []
        if type(parent) != tuple:
            for i, j in [
                (-1, 0),
                (0, -1),
                (1, 0),
                (0, 1),
                (-1, -1),
                (-1, 1),
                (1, -1),
                (1, 1),
            ]:
                if not self.blocked(cx, cy, i, j):
                    neighbours.append((cx + i, cy + j))

            return neighbours
        dx, dy = self.direction(cx, cy, parent[0], parent[1])

        if dx != 0 and dy != 0:
            if not self.blocked(cx, cy, 0, dy):
                neighbours.append((cx, cy + dy))
            if not self.blocked(cx, cy, dx, 0):
                neighbours.append((cx + dx, cy))
            if (
                not self.blocked(cx, cy, 0, dy) or not self.blocked(cx, cy, dx, 0)
            ) and not self.blocked(cx, cy, dx, dy):
                neighbours.append((cx + dx, cy + dy))
            if self.blocked(cx, cy, -dx, 0) and not self.blocked(cx, cy, 0, dy):
                neighbours.append((cx - dx, cy + dy))
            if self.blocked(cx, cy, 0, -dy) and not self.blocked(cx, cy, dx, 0):
                neighbours.append((cx + dx, cy - dy))

        else:
            if dx == 0:
                if not self.blocked(cx, cy, dx, 0):
                    if not self.blocked(cx, cy, 0, dy):
                        neighbours.append((cx, cy + dy))
                    if self.blocked(cx, cy, 1, 0):
                        neighbours.append((cx + 1, cy + dy))
                    if self.blocked(cx, cy, -1, 0):
                        neighbours.append((cx - 1, cy + dy))

            else:
                if not self.blocked(cx, cy, dx, 0):
                    if not self.blocked(cx, cy, dx, 0):
                        neighbours.append((cx + dx, cy))
                    if self.blocked(cx, cy, 0, 1):
                        neighbours.append((cx + dx, cy + 1))
                    if self.blocked(cx, cy, 0, -1):
                        neighbours.append((cx + dx, cy - 1))
        return neighbours

    def jump(self, cx, cy, dx, dy, goal):
        nx = cx + dx
        ny = cy + dy
        if self.blocked(nx, ny, 0, 0):
            return None

        if (nx, ny) == goal:
            return nx, ny

        ox = nx
        oy = ny

        if dx != 0 and dy != 0:
            while True:
                if (
                    not self.blocked(ox, oy, -dx, dy)
                    and self.blocked(ox, oy, -dx, 0)
                    or not self.blocked(ox, oy, dx, -dy)
                    and self.blocked(ox, oy, 0, -dy)
                ):
                    return ox, oy

                if (
                    self.jump(ox, oy, dx, 0, goal) is not None
                    or self.jump(ox, oy, 0, dy, goal) is not None
                ):
                    return ox, oy

                ox += dx
                oy += dy

                if self.blocked(ox, oy, 0, 0):
                    return None

                if self.dblock(ox, oy, dx, dy):
                    return None

                if (ox, oy) == goal:
                    return ox, oy
        else:
            if dx != 0:
                while True:
                    if (
                        not self.blocked(ox, ny, dx, 1)
                        and self.blocked(ox, ny, 0, 1)
                        or not self.blocked(ox, ny, dx, -1)
                        and self.blocked(ox, ny, 0, -1)
                    ):
                        return ox, ny

                    ox += dx

                    if self.blocked(ox, ny, 0, 0):
                        return None

                    if (ox, ny) == goal:
                        return ox, ny

            else:
                while True:
                    if (
                        not self.blocked(nx, oy, 1, dy)
                        and self.blocked(nx, oy, 1, 0)
                        or not self.blocked(nx, oy, -1, dy)
                        and self.blocked(nx, oy, -1, 0)
                    ):
                        return nx, oy

                    oy += dy

                    if self.blocked(nx, oy, 0, 0):
                        return None

                    if (nx, oy) == goal:
                        return nx, oy

        return self.jump(nx, ny, dx, dy, goal)

    def identify_successors(self, cx, cy, came_from, goal):
        successors = []
        neighbours = self.node_neighbours(cx, cy, came_from.get((cx, cy), 0))

        for cell in neighbours:
            dx = cell[0] - cx
            dy = cell[1] - cy

            jump_point = self.jump(cx, cy, dx, dy, goal)

            if jump_point is not None:
                successors.append(jump_point)

        return successors

    def get_path(self, start, goal, hchoice=EUCLIDEAN):
        start = np.round(start)
        goal = np.round(goal)
        start = (int(start[0]), int(start[1]))
        goal = (int(goal[0]), int(goal[1]))
        logger.debug("Finding path from {} to {}".format(start, goal))
        start_time = time.time()

        came_from = {}
        close_set = set()
        gscore = {start: 0}
        fscore = {start: self.heuristic(start, goal, hchoice)}

        pqueue = []

        heapq.heappush(pqueue, (fscore[start], start))

        while pqueue:
            current = heapq.heappop(pqueue)[1]
            if current == goal:
                data = []
                while current in came_from:
                    data.append(current)
                    current = came_from[current]
                data.append(start)
                data = data[::-1]
                logger.debug(
                    "Got path from {} to {} with score {} in {:.02f}".format(
                        start, goal, gscore[goal], time.time() - start_time
                    )
                )
                return data

            close_set.add(current)

            successors = self.identify_successors(
                current[0], current[1], came_from, goal
            )

            for successor in successors:
                jump_point = successor

                if (
                    jump_point in close_set
                ):  # and tentative_g_score >= gscore.get(jump_point,0):
                    continue

                tentative_g_score = gscore[current] + self.lenght(
                    current, jump_point, hchoice
                )

                if tentative_g_score < gscore.get(jump_point, 0) or jump_point not in [
                    j[1] for j in pqueue
                ]:
                    came_from[jump_point] = current
                    gscore[jump_point] = tentative_g_score
                    fscore[jump_point] = tentative_g_score + self.heuristic(
                        jump_point, goal, hchoice
                    )
                    heapq.heappush(pqueue, (fscore[jump_point], jump_point))
        return False

    def lenght(self, current, jumppoint, hchoice):
        dx, dy = self.direction(current[0], current[1], jumppoint[0], jumppoint[1])
        dx = math.fabs(dx)
        dy = math.fabs(dy)
        lx = math.fabs(current[0] - jumppoint[0])
        ly = math.fabs(current[1] - jumppoint[1])
        if hchoice == MANHATTAN:
            if dx != 0 and dy != 0:
                lenght = lx * 14
                return lenght
            else:
                lenght = (dx * lx + dy * ly) * 10
                return lenght
        if hchoice == EUCLIDEAN:
            return math.sqrt(
                (current[0] - jumppoint[0]) ** 2 + (current[1] - jumppoint[1]) ** 2
            )
