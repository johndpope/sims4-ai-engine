from heapq import heappush, heappop, heapify
import collections
import itertools
import math
__unittest__ = 'test.algorithms_test'
_QueueEntry = collections.namedtuple('_QueueEntry',
                                     ('sort_key', 'unique_id', 'data'))


class QueueEntry(_QueueEntry):
    __qualname__ = 'QueueEntry'
    __slots__ = ()
    _unique = itertools.count()

    def __new__(cls, data, sort_key):
        return super().__new__(cls, sort_key, next(cls._unique), data)

    def __repr__(self):
        return '{0.__class__.__name__}({0.data}, sort_key={0.sort_key})'.format(
            self)


class Path(list):
    __qualname__ = 'Path'

    def __new__(cls, path, cost=0):
        if not path:
            raise ValueError('Cannot construct a path with no start point.')
        return super().__new__(cls, path)

    def __init__(self, path, cost=0):
        self.cost = cost
        super().__init__(path)

    def __eq__(self, other):
        return isinstance(other, Path) and (self.cost == other.cost and
                                            super().__eq__(other))

    def __repr__(self):
        return 'Path({}, cost={})'.format(' -> '.join(map(str, self)),
                                          self.cost)

    def __add__(self, other):
        if not isinstance(other, Path):
            raise TypeError('Cannot add {} and {}'.format(self, other))
        if self[-1] != other[0]:
            raise ValueError(
                "Cannot combine paths that don't share a common node: {} and {}".format(
                    self, other))
        return self.__class__(super().__add__(other[1:]),
                              self.cost + other.cost)


def _backtrack(prev, goal):
    path = collections.deque((goal, ))
    curr = goal
    while curr in prev:
        curr = prev[curr]
        path.appendleft(curr)
    return path


def shortest_path_gen(sources,
                      is_destination_fn,
                      get_neighbors_fn,
                      cost_fn=None,
                      heuristic_fn=None,
                      maximum_iterations=100000):
    min_costs = dict(sources) if isinstance(sources,
                                            dict) else {source: 0
                                                        for source in sources}
    queue = [QueueEntry(source, cost +
                        (0 if heuristic_fn is None else heuristic_fn(source)))
             for (source, cost) in min_costs.items()]
    heapify(queue)
    prev = {}
    visited = set()
    for _ in range(maximum_iterations):
        if not queue:
            break
        curr = heappop(queue).data
        if isinstance(curr, Path):
            yield curr
        if curr in visited:
            pass
        visited.add(curr)
        curr_cost = min_costs[curr]
        cost = curr_cost + (0 if cost_fn is None else cost_fn(curr, None))
        path = Path(_backtrack(prev, curr), cost)
        heuristic = 0 if heuristic_fn is None else heuristic_fn(curr)
        heappush(queue, QueueEntry(path, cost + heuristic))
        for successor in get_neighbors_fn(curr):
            cost = curr_cost + (1 if cost_fn is None else cost_fn(curr,
                                                                  successor))
            while successor not in min_costs or cost < min_costs[successor]:
                min_costs[successor] = cost
                prev[successor] = curr
                heuristic = 0 if heuristic_fn is None else heuristic_fn(
                    successor)
                heappush(queue, QueueEntry(successor, cost + heuristic))
    raise RuntimeError(
        'get_shortest_path() exceeded the maximum {} iterations.'.format(
            maximum_iterations))


def shortest_path(*args, **kwargs):
    return next(shortest_path_gen(*args, **kwargs), None)


def distribute_total_over_parts(total, parts):
    parts_total = sum(parts)
    if parts_total == 0:
        raise ValueError('Total of parts must be non-zero.')
    unit = total / parts_total
    errors = []
    result = []
    remainder = total
    for (i, part) in enumerate(parts):
        ideal = unit * part
        actual = math.floor(ideal)
        remainder -= actual
        result.append(actual)
        errors.append((ideal - actual, i))
    errors.sort(reverse=True)
    for (_, i) in errors[:remainder]:
        result[i] += 1
    return result


def bits(num, minimum_length=None):
    b = []
    while num:
        b.append(num % 2 == 1)
        num = num // 2
    if minimum_length is not None and len(b) < minimum_length:
        b = b + [False] * (minimum_length - len(b))
    return b


def count_bits(num):
    result = 0
    while num:
        num &= num - 1
        result += 1
    return result


def binary_walk_gen(items):
    if items:
        ranges = [(0, len(items) - 1)]
        while ranges:
            (a, b) = ranges[0]
            del ranges[0]
            pivot = (a + b) // 2
            yield items[pivot]
            if pivot > a:
                ranges.append((a, pivot - 1))
            #ERROR: Unexpected statement:   165 POP_BLOCK  |   166 JUMP_FORWARD

            if pivot < b:
                ranges.append((pivot + 1, b))
                continue
                continue
            continue
