from heapq import heappop, heappush

import numpy as np


class AAlgorithm:
    def __init__(self, map_array):
        self.array = map_array

    def heuristic(self, a, b):
        # Euclidean distance squared heuristic
        # return ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
        # Euclidean distance heuristic
        return ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5

    def get_path(self, start, goal):
        start = np.round(start)
        goal = np.round(goal)
        start = (int(start[0]), int(start[1]))
        goal = (int(goal[0]), int(goal[1]))

        neighbors = (
            (0, 1),
            (0, -1),
            (1, 0),
            (-1, 0),
            (1, 1),
            (1, -1),
            (-1, 1),
            (-1, -1),
        )

        close_set = set()
        came_from = {}
        gscore = {start: 0}
        fscore = {start: self.heuristic(start, goal)}
        oheap = []

        heappush(oheap, (fscore[start], start))

        while oheap:
            current = heappop(oheap)[1]
            if current == goal:
                data = []
                while current in came_from:
                    data.append(current)
                    current = came_from[current]
                return data[::-1]

            close_set.add(current)
            for i, j in neighbors:
                neighbor = current[0] + i, current[1] + j
                tentative_g_score = gscore[current] + self.heuristic(current, neighbor)
                if 0 <= neighbor[0] < self.array.shape[0]:
                    if 0 <= neighbor[1] < self.array.shape[1]:
                        # if not all([self.array[current[0] + i*d][current[1] + j*d] for d in range(1, 9)]):
                        if self.array[neighbor[0]][neighbor[1]] == 0:
                            continue
                    else:
                        # array bound y walls
                        continue
                else:
                    # array bound x walls
                    continue

                if neighbor in close_set and tentative_g_score >= gscore.get(
                    neighbor, 0
                ):
                    continue
                if tentative_g_score < gscore.get(neighbor, 0) or neighbor not in [
                    i[1] for i in oheap
                ]:
                    came_from[neighbor] = current
                    gscore[neighbor] = tentative_g_score
                    fscore[neighbor] = tentative_g_score + self.heuristic(
                        neighbor, goal
                    )
                    heappush(oheap, (fscore[neighbor], neighbor))

        return False
