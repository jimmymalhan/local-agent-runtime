"""TDD tests for PathFinder on directed weighted graphs."""

import unittest
from collections import defaultdict, deque
import heapq
import itertools


class PathFinder:
    """Directed weighted graph path finder."""

    def __init__(self):
        self.graph = defaultdict(list)

    def add_edge(self, src, dst, weight=1):
        self.graph[src].append((dst, weight))
        if dst not in self.graph:
            self.graph[dst]

    def bfs_path(self, start, end):
        """Return the first path found via BFS (fewest edges), or None."""
        if start == end:
            return [start]
        visited = {start}
        queue = deque([(start, [start])])
        while queue:
            node, path = queue.popleft()
            for neighbor, _ in self.graph[node]:
                if neighbor == end:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return None

    def dfs_path(self, start, end):
        """Return the first path found via DFS, or None."""
        if start == end:
            return [start]
        visited = set()

        def _dfs(node, path):
            visited.add(node)
            for neighbor, _ in self.graph[node]:
                if neighbor == end:
                    return path + [neighbor]
                if neighbor not in visited:
                    result = _dfs(neighbor, path + [neighbor])
                    if result is not None:
                        return result
            return None

        return _dfs(start, [start])

    def all_paths(self, start, end):
        """Return all simple paths from start to end."""
        if start == end:
            return [[start]]
        results = []

        def _backtrack(node, path, visited):
            for neighbor, _ in self.graph[node]:
                if neighbor == end:
                    results.append(path + [neighbor])
                elif neighbor not in visited:
                    visited.add(neighbor)
                    _backtrack(neighbor, path + [neighbor], visited)
                    visited.discard(neighbor)

        _backtrack(start, [start], {start})
        return results

    def shortest_path(self, start, end):
        """Dijkstra's algorithm. Returns (distance, path) or (float('inf'), None)."""
        if start == end:
            return (0, [start])
        dist = {start: 0}
        prev = {start: None}
        heap = [(0, start)]
        while heap:
            d, node = heapq.heappop(heap)
            if node == end:
                path = []
                cur = end
                while cur is not None:
                    path.append(cur)
                    cur = prev[cur]
                return (d, path[::-1])
            if d > dist.get(node, float('inf')):
                continue
            for neighbor, weight in self.graph[node]:
                nd = d + weight
                if nd < dist.get(neighbor, float('inf')):
                    dist[neighbor] = nd
                    prev[neighbor] = node
                    heapq.heappush(heap, (nd, neighbor))
        return (float('inf'), None)


class TestBFSPath(unittest.TestCase):
    """Tests for bfs_path."""

    def test_simple_path(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "C", 1)
        self.assertEqual(pf.bfs_path("A", "C"), ["A", "B", "C"])

    def test_direct_edge(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 5)
        self.assertEqual(pf.bfs_path("A", "B"), ["A", "B"])

    def test_start_equals_end(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        self.assertEqual(pf.bfs_path("A", "A"), ["A"])

    def test_no_path(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("C", "D", 1)
        self.assertIsNone(pf.bfs_path("A", "D"))

    def test_disconnected_node(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        self.assertIsNone(pf.bfs_path("B", "A"))

    def test_bfs_finds_fewest_edges(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("A", "C", 1)
        pf.add_edge("B", "D", 1)
        pf.add_edge("C", "D", 1)
        pf.add_edge("A", "D", 1)
        path = pf.bfs_path("A", "D")
        self.assertEqual(len(path), 2)
        self.assertEqual(path, ["A", "D"])

    def test_cycle_does_not_loop(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "C", 1)
        pf.add_edge("C", "A", 1)
        pf.add_edge("C", "D", 1)
        self.assertEqual(pf.bfs_path("A", "D"), ["A", "B", "C", "D"])

    def test_self_loop(self):
        pf = PathFinder()
        pf.add_edge("A", "A", 1)
        pf.add_edge("A", "B", 1)
        self.assertEqual(pf.bfs_path("A", "B"), ["A", "B"])

    def test_nonexistent_start(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        self.assertIsNone(pf.bfs_path("Z", "B"))

    def test_nonexistent_end(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        self.assertIsNone(pf.bfs_path("A", "Z"))


class TestDFSPath(unittest.TestCase):
    """Tests for dfs_path."""

    def test_simple_path(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "C", 1)
        result = pf.dfs_path("A", "C")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "A")
        self.assertEqual(result[-1], "C")

    def test_start_equals_end(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        self.assertEqual(pf.dfs_path("A", "A"), ["A"])

    def test_no_path(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("C", "D", 1)
        self.assertIsNone(pf.dfs_path("A", "D"))

    def test_cycle_does_not_loop(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "C", 1)
        pf.add_edge("C", "A", 1)
        pf.add_edge("C", "D", 1)
        result = pf.dfs_path("A", "D")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "A")
        self.assertEqual(result[-1], "D")
        self.assertEqual(len(set(result)), len(result))

    def test_returns_valid_path(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("A", "C", 1)
        pf.add_edge("B", "D", 1)
        pf.add_edge("C", "D", 1)
        result = pf.dfs_path("A", "D")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "A")
        self.assertEqual(result[-1], "D")
        for i in range(len(result) - 1):
            neighbors = [n for n, _ in pf.graph[result[i]]]
            self.assertIn(result[i + 1], neighbors)

    def test_directed_edge_respected(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        self.assertIsNone(pf.dfs_path("B", "A"))

    def test_deep_chain(self):
        pf = PathFinder()
        nodes = list(range(100))
        for i in range(99):
            pf.add_edge(i, i + 1, 1)
        result = pf.dfs_path(0, 99)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 0)
        self.assertEqual(result[-1], 99)


class TestAllPaths(unittest.TestCase):
    """Tests for all_paths."""

    def test_single_path(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "C", 1)
        paths = pf.all_paths("A", "C")
        self.assertEqual(paths, [["A", "B", "C"]])

    def test_multiple_paths(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("A", "C", 1)
        pf.add_edge("B", "D", 1)
        pf.add_edge("C", "D", 1)
        paths = pf.all_paths("A", "D")
        self.assertEqual(len(paths), 2)
        self.assertIn(["A", "B", "D"], paths)
        self.assertIn(["A", "C", "D"], paths)

    def test_no_path(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("C", "D", 1)
        paths = pf.all_paths("A", "D")
        self.assertEqual(paths, [])

    def test_start_equals_end(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        paths = pf.all_paths("A", "A")
        self.assertEqual(paths, [["A"]])

    def test_cycle_no_duplicates(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "C", 1)
        pf.add_edge("C", "A", 1)
        pf.add_edge("B", "D", 1)
        pf.add_edge("C", "D", 1)
        paths = pf.all_paths("A", "D")
        for path in paths:
            self.assertEqual(len(set(path)), len(path), "Path has repeated nodes")

    def test_diamond_graph(self):
        pf = PathFinder()
        pf.add_edge("S", "A", 1)
        pf.add_edge("S", "B", 1)
        pf.add_edge("A", "C", 1)
        pf.add_edge("B", "C", 1)
        pf.add_edge("A", "B", 1)
        paths = pf.all_paths("S", "C")
        self.assertEqual(len(paths), 3)
        self.assertIn(["S", "A", "C"], paths)
        self.assertIn(["S", "B", "C"], paths)
        self.assertIn(["S", "A", "B", "C"], paths)

    def test_disconnected_graph(self):
        pf = PathFinder()
        pf.add_edge(1, 2, 1)
        pf.add_edge(2, 3, 1)
        pf.add_edge(4, 5, 1)
        pf.add_edge(5, 6, 1)
        self.assertEqual(pf.all_paths(1, 6), [])
        self.assertEqual(pf.all_paths(1, 3), [[1, 2, 3]])
        self.assertEqual(pf.all_paths(4, 6), [[4, 5, 6]])

    def test_complex_dag(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("A", "C", 1)
        pf.add_edge("A", "D", 1)
        pf.add_edge("B", "E", 1)
        pf.add_edge("C", "E", 1)
        pf.add_edge("D", "E", 1)
        pf.add_edge("B", "C", 1)
        pf.add_edge("C", "D", 1)
        paths = pf.all_paths("A", "E")
        self.assertTrue(len(paths) >= 5)
        for path in paths:
            self.assertEqual(path[0], "A")
            self.assertEqual(path[-1], "E")
            self.assertEqual(len(set(path)), len(path))


class TestShortestPath(unittest.TestCase):
    """Tests for shortest_path (Dijkstra)."""

    def test_simple_weighted(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "C", 2)
        pf.add_edge("A", "C", 10)
        dist, path = pf.shortest_path("A", "C")
        self.assertEqual(dist, 3)
        self.assertEqual(path, ["A", "B", "C"])

    def test_direct_is_shortest(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("A", "C", 2)
        pf.add_edge("B", "C", 5)
        dist, path = pf.shortest_path("A", "C")
        self.assertEqual(dist, 2)
        self.assertEqual(path, ["A", "C"])

    def test_start_equals_end(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        dist, path = pf.shortest_path("A", "A")
        self.assertEqual(dist, 0)
        self.assertEqual(path, ["A"])

    def test_no_path(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("C", "D", 1)
        dist, path = pf.shortest_path("A", "D")
        self.assertEqual(dist, float('inf'))
        self.assertIsNone(path)

    def test_directed_no_reverse(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        dist, path = pf.shortest_path("B", "A")
        self.assertEqual(dist, float('inf'))
        self.assertIsNone(path)

    def test_longer_path_cheaper(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 100)
        pf.add_edge("A", "C", 1)
        pf.add_edge("C", "D", 1)
        pf.add_edge("D", "B", 1)
        dist, path = pf.shortest_path("A", "B")
        self.assertEqual(dist, 3)
        self.assertEqual(path, ["A", "C", "D", "B"])

    def test_cycle_handled(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "C", 1)
        pf.add_edge("C", "A", 1)
        pf.add_edge("C", "D", 1)
        dist, path = pf.shortest_path("A", "D")
        self.assertEqual(dist, 3)
        self.assertEqual(path, ["A", "B", "C", "D"])

    def test_multiple_equal_weight_paths(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("A", "C", 1)
        pf.add_edge("B", "D", 1)
        pf.add_edge("C", "D", 1)
        dist, path = pf.shortest_path("A", "D")
        self.assertEqual(dist, 2)
        self.assertEqual(len(path), 3)

    def test_large_graph(self):
        pf = PathFinder()
        n = 500
        for i in range(n - 1):
            pf.add_edge(i, i + 1, 1)
        for i in range(0, n - 2, 2):
            pf.add_edge(i, i + 2, 3)
        dist, path = pf.shortest_path(0, n - 1)
        self.assertEqual(dist, n - 1)
        self.assertEqual(path[0], 0)
        self.assertEqual(path[-1], n - 1)

    def test_disconnected_components(self):
        pf = PathFinder()
        for i in range(5):
            pf.add_edge(i, i + 1, 1)
        for i in range(100, 105):
            pf.add_edge(i, i + 1, 1)
        dist, path = pf.shortest_path(0, 105)
        self.assertEqual(dist, float('inf'))
        self.assertIsNone(path)
        dist2, path2 = pf.shortest_path(100, 105)
        self.assertEqual(dist2, 5)

    def test_heavy_vs_light_edges(self):
        pf = PathFinder()
        pf.add_edge("S", "A", 1)
        pf.add_edge("S", "B", 5)
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "T", 1)
        pf.add_edge("A", "T", 10)
        dist, path = pf.shortest_path("S", "T")
        self.assertEqual(dist, 3)
        self.assertEqual(path, ["S", "A", "B", "T"])

    def test_single_node_graph(self):
        pf = PathFinder()
        pf.add_edge("X", "X", 5)
        dist, path = pf.shortest_path("X", "X")
        self.assertEqual(dist, 0)
        self.assertEqual(path, ["X"])


class TestLargeGraph(unittest.TestCase):
    """Stress tests on larger graphs."""

    def test_large_chain_bfs(self):
        pf = PathFinder()
        n = 1000
        for i in range(n - 1):
            pf.add_edge(i, i + 1, 1)
        path = pf.bfs_path(0, n - 1)
        self.assertIsNotNone(path)
        self.assertEqual(len(path), n)

    def test_large_chain_dfs(self):
        pf = PathFinder()
        n = 500
        for i in range(n - 1):
            pf.add_edge(i, i + 1, 1)
        path = pf.dfs_path(0, n - 1)
        self.assertIsNotNone(path)
        self.assertEqual(path[0], 0)
        self.assertEqual(path[-1], n - 1)

    def test_wide_graph_all_paths(self):
        pf = PathFinder()
        for i in range(10):
            pf.add_edge("S", f"M{i}", 1)
            pf.add_edge(f"M{i}", "T", 1)
        paths = pf.all_paths("S", "T")
        self.assertEqual(len(paths), 10)

    def test_dense_small_graph_all_paths(self):
        pf = PathFinder()
        nodes = ["A", "B", "C", "D"]
        for i, src in enumerate(nodes):
            for dst in nodes[i + 1:]:
                pf.add_edge(src, dst, 1)
        paths = pf.all_paths("A", "D")
        self.assertTrue(len(paths) >= 4)

    def test_large_dijkstra_grid(self):
        pf = PathFinder()
        size = 20
        for r in range(size):
            for c in range(size):
                node = r * size + c
                if c + 1 < size:
                    pf.add_edge(node, node + 1, 1)
                if r + 1 < size:
                    pf.add_edge(node, node + size, 1)
        dist, path = pf.shortest_path(0, size * size - 1)
        self.assertEqual(dist, 2 * (size - 1))
        self.assertIsNotNone(path)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and corner cases."""

    def test_empty_graph(self):
        pf = PathFinder()
        self.assertIsNone(pf.bfs_path("A", "B"))
        self.assertIsNone(pf.dfs_path("A", "B"))
        self.assertEqual(pf.all_paths("A", "B"), [])
        dist, path = pf.shortest_path("A", "B")
        self.assertEqual(dist, float('inf'))

    def test_integer_nodes(self):
        pf = PathFinder()
        pf.add_edge(1, 2, 3)
        pf.add_edge(2, 3, 4)
        self.assertEqual(pf.bfs_path(1, 3), [1, 2, 3])
        dist, path = pf.shortest_path(1, 3)
        self.assertEqual(dist, 7)

    def test_self_loop_all_paths(self):
        pf = PathFinder()
        pf.add_edge("A", "A", 1)
        pf.add_edge("A", "B", 2)
        paths = pf.all_paths("A", "B")
        self.assertEqual(paths, [["A", "B"]])

    def test_parallel_edges(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 10)
        pf.add_edge("A", "B", 1)
        dist, path = pf.shortest_path("A", "B")
        self.assertEqual(dist, 1)

    def test_bidirectional_edges(self):
        pf = PathFinder()
        pf.add_edge("A", "B", 1)
        pf.add_edge("B", "A", 1)
        pf.add_edge("B", "C", 1)
        self.assertEqual(pf.bfs_path("A", "C"), ["A", "B", "C"])
        dist, _ = pf.shortest_path("A", "C")
        self.assertEqual(dist, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
