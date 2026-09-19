"""Review the resolved working ancestry graph without deleting source claims."""
from collections import defaultdict
import sqlite3


def working_graph_signals(connection: sqlite3.Connection) -> dict[int, set[str]]:
    """Find cycles and contradictory explicit roles in O(people + edges).

    Only accepted working parent edges participate. Unspecified parent roles do
    not compete. Repeated evidence for the same parent and role is legitimate.
    Iterative strongly connected components avoid recursion limits on deep trees.
    """
    rows = connection.execute("""
        SELECT DISTINCT r.relationship_assertion_id, r.subject_person_id,
               r.object_person_id, r.role
        FROM relationship_assertion r JOIN conclusion c
          ON c.chosen_relationship_assertion_id = r.relationship_assertion_id
        WHERE r.predicate = 'parent_child' AND c.confidence = 'accepted_working'
    """).fetchall()
    signals: dict[int, set[str]] = defaultdict(set)
    graph: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    slots: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    roles: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for edge, parent, child, role in rows:
        graph[parent].add(child)
        graph.setdefault(child, set())
        reverse[child].add(parent)
        reverse.setdefault(parent, set())
        if role is not None:
            slots[(child, role)][parent].append(edge)
            roles[(parent, child)][role].append(edge)
        if parent == child:
            signals[edge].add('self_parent')
    for groups, code in ((slots, 'competing_parent_choices'), (roles, 'conflicting_parent_roles')):
        for alternatives in groups.values():
            if len(alternatives) > 1:
                for edges in alternatives.values():
                    for edge in edges:
                        signals[edge].add(code)
    visited: set[str] = set()
    order: list[str] = []
    for start in graph:
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(graph[start]))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                order.append(node)
                stack.pop()
            elif child not in visited:
                visited.add(child)
                stack.append((child, iter(graph[child])))
    components: dict[str, int] = {}
    sizes: dict[int, int] = defaultdict(int)
    for start in reversed(order):
        if start in components:
            continue
        component = len(sizes)
        pending = [start]
        components[start] = component
        while pending:
            node = pending.pop()
            sizes[component] += 1
            for parent in reverse[node]:
                if parent not in components:
                    components[parent] = component
                    pending.append(parent)
    for edge, parent, child, _ in rows:
        if components[parent] == components[child] and sizes[components[parent]] > 1:
            signals[edge].add('ancestry_cycle')
    return dict(signals)


def require_consistent_working_graph(connection: sqlite3.Connection) -> None:
    signals = working_graph_signals(connection)
    if signals:
        codes = sorted({code for values in signals.values() for code in values})
        raise ValueError('Invalid working parent graph: ' + ', '.join(codes) + '; the entire batch was not imported')


def quarantine_working_conflicts(connection: sqlite3.Connection) -> None:
    """Retain every imported claim, withdrawing inconsistent working edges."""
    for edge, codes in working_graph_signals(connection).items():
        connection.execute("""
            UPDATE conclusion SET confidence = 'quarantined_contradiction',
                rationale = rationale || ?, updated_at = CURRENT_TIMESTAMP
            WHERE chosen_relationship_assertion_id = ?
        """, (' Review signals: ' + ', '.join(sorted(codes)) + '.', edge))
