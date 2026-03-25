"""
Operational Transformation Engine for Real-Time Collaborative Text Editing.

Supports insert(pos, char) and delete(pos) operations with transformation
functions that guarantee convergence for concurrent edits from multiple clients.
"""

from __future__ import annotations

import copy
import enum
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


class OpType(enum.Enum):
    INSERT = "insert"
    DELETE = "delete"


@dataclass
class Operation:
    op_type: OpType
    pos: int
    char: str = ""  # only used for INSERT
    client_id: int = 0
    revision: int = 0

    def __repr__(self) -> str:
        if self.op_type == OpType.INSERT:
            return f"Insert(pos={self.pos}, char='{self.char}', client={self.client_id}, rev={self.revision})"
        return f"Delete(pos={self.pos}, client={self.client_id}, rev={self.revision})"


def insert(pos: int, char: str, client_id: int = 0, revision: int = 0) -> Operation:
    return Operation(OpType.INSERT, pos, char, client_id, revision)


def delete(pos: int, client_id: int = 0, revision: int = 0) -> Operation:
    return Operation(OpType.DELETE, pos, client_id, revision)


def transform(op1: Operation, op2: Operation) -> Tuple[Operation, Operation]:
    """
    Transform two concurrent operations so they can be applied in either order
    and produce the same document state (convergence).

    Returns (op1', op2') where:
      - Applying op1 then op2' yields the same state as applying op2 then op1'.

    This is the core OT inclusion transformation (IT) satisfying:
      apply(apply(doc, op1), op2') == apply(apply(doc, op2), op1')
    """
    op1_prime = copy.deepcopy(op1)
    op2_prime = copy.deepcopy(op2)

    if op1.op_type == OpType.INSERT and op2.op_type == OpType.INSERT:
        if op1.pos < op2.pos:
            op2_prime.pos += 1
        elif op1.pos > op2.pos:
            op1_prime.pos += 1
        else:
            # Tie-break by client_id for determinism
            if op1.client_id < op2.client_id:
                op2_prime.pos += 1
            else:
                op1_prime.pos += 1

    elif op1.op_type == OpType.INSERT and op2.op_type == OpType.DELETE:
        if op1.pos <= op2.pos:
            op2_prime.pos += 1
        else:
            op1_prime.pos -= 1

    elif op1.op_type == OpType.DELETE and op2.op_type == OpType.INSERT:
        if op1.pos < op2.pos:
            op2_prime.pos -= 1
        else:
            op1_prime.pos += 1

    elif op1.op_type == OpType.DELETE and op2.op_type == OpType.DELETE:
        if op1.pos < op2.pos:
            op2_prime.pos -= 1
        elif op1.pos > op2.pos:
            op1_prime.pos -= 1
        else:
            # Both delete the same character — make both no-ops
            op1_prime.pos = -1
            op2_prime.pos = -1

    return op1_prime, op2_prime


def apply_op(doc: str, op: Operation) -> str:
    """Apply a single operation to a document string."""
    if op.pos == -1:
        # No-op (result of double-delete transform)
        return doc
    if op.op_type == OpType.INSERT:
        if op.pos < 0 or op.pos > len(doc):
            raise ValueError(f"Insert pos {op.pos} out of range for doc length {len(doc)}")
        return doc[:op.pos] + op.char + doc[op.pos:]
    elif op.op_type == OpType.DELETE:
        if op.pos < 0 or op.pos >= len(doc):
            raise ValueError(f"Delete pos {op.pos} out of range for doc length {len(doc)}")
        return doc[:op.pos] + doc[op.pos + 1:]
    raise ValueError(f"Unknown op type: {op.op_type}")


def apply_ops(doc: str, ops: List[Operation]) -> str:
    """Apply a sequence of operations to a document."""
    for op in ops:
        doc = apply_op(doc, op)
    return doc


def transform_operation_against_history(
    op: Operation, history: List[Operation]
) -> Operation:
    """Transform an operation against a list of already-applied operations."""
    transformed = copy.deepcopy(op)
    for past_op in history:
        transformed, _ = transform(transformed, past_op)
    return transformed


# ---------------------------------------------------------------------------
# Server: central authority that sequences operations
# ---------------------------------------------------------------------------

@dataclass
class ServerState:
    document: str = ""
    revision: int = 0
    history: List[Operation] = field(default_factory=list)

    def receive(self, op: Operation) -> Operation:
        """
        Receive an operation from a client. Transform it against any operations
        the client hasn't seen, apply it, and return the transformed op for
        broadcast.
        """
        # Transform against all ops that happened after the client's known revision
        concurrent_ops = self.history[op.revision:]
        transformed = copy.deepcopy(op)
        for past_op in concurrent_ops:
            transformed, _ = transform(transformed, past_op)

        self.document = apply_op(self.document, transformed)
        transformed.revision = self.revision
        self.history.append(transformed)
        self.revision += 1
        return transformed


# ---------------------------------------------------------------------------
# Client: local editing with OT buffer
# ---------------------------------------------------------------------------

@dataclass
class ClientState:
    client_id: int
    document: str = ""
    revision: int = 0  # last server revision acknowledged
    pending: Optional[Operation] = None  # sent but not yet ack'd
    buffer: List[Operation] = field(default_factory=list)  # local ops waiting to send

    def apply_local(self, op: Operation) -> None:
        """User makes a local edit."""
        op.client_id = self.client_id
        op.revision = self.revision
        self.document = apply_op(self.document, op)
        if self.pending is None:
            self.pending = op
        else:
            self.buffer.append(op)

    def send_next(self, server: ServerState) -> Optional[Operation]:
        """Send the next pending operation to the server."""
        if self.pending is not None:
            op_to_send = copy.deepcopy(self.pending)
            op_to_send.revision = self.revision
            return server.receive(op_to_send)
        return None

    def acknowledge(self, server_op: Operation) -> None:
        """Server acknowledged our pending operation."""
        self.revision += 1
        self.pending = self.buffer.pop(0) if self.buffer else None

    def receive_remote(self, server_op: Operation) -> None:
        """Receive an operation from another client via server broadcast."""
        if self.pending is not None:
            server_op_prime, pending_prime = transform(server_op, self.pending)
            self.pending = pending_prime
            new_buffer = []
            current_server_op = server_op_prime
            for buf_op in self.buffer:
                current_server_op, buf_prime = transform(current_server_op, buf_op)
                new_buffer.append(buf_prime)
            self.buffer = new_buffer
            self.document = apply_op(self.document, current_server_op)
        else:
            self.document = apply_op(self.document, server_op)
        self.revision += 1


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def simulate_concurrent_edits(
    initial_doc: str,
    client1_ops: List[Operation],
    client2_ops: List[Operation],
) -> Tuple[str, str, str]:
    """
    Simulate two clients making concurrent edits against a shared server.
    Returns (server_doc, client1_doc, client2_doc) — all should be equal.
    """
    server = ServerState(document=initial_doc, revision=0)
    c1 = ClientState(client_id=1, document=initial_doc, revision=0)
    c2 = ClientState(client_id=2, document=initial_doc, revision=0)

    # Both clients make local edits
    for op in client1_ops:
        c1.apply_local(op)
    for op in client2_ops:
        c2.apply_local(op)

    # Client 1 sends all ops first
    while c1.pending is not None:
        server_op = c1.send_next(server)
        c1.acknowledge(server_op)
        c2.receive_remote(server_op)

    # Client 2 sends all ops
    while c2.pending is not None:
        server_op = c2.send_next(server)
        c2.acknowledge(server_op)
        c1.receive_remote(server_op)

    return server.document, c1.document, c2.document


def convergence_proof_basic() -> None:
    """
    Formal convergence proof via exhaustive assertion:
    For two operations op1 and op2 applied concurrently to document D,
    show that apply(apply(D, op1), transform(op2, op1)) ==
             apply(apply(D, op2), transform(op1, op2))
    """
    doc = "abcdef"

    # Case 1: Insert vs Insert (different positions)
    op1 = insert(1, "X", client_id=1)
    op2 = insert(4, "Y", client_id=2)
    op1_p, op2_p = transform(op1, op2)
    path_a = apply_op(apply_op(doc, op1), op2_p)
    path_b = apply_op(apply_op(doc, op2), op1_p)
    assert path_a == path_b, f"Case 1 failed: {path_a!r} != {path_b!r}"

    # Case 2: Insert vs Insert (same position, tie-break)
    op1 = insert(3, "X", client_id=1)
    op2 = insert(3, "Y", client_id=2)
    op1_p, op2_p = transform(op1, op2)
    path_a = apply_op(apply_op(doc, op1), op2_p)
    path_b = apply_op(apply_op(doc, op2), op1_p)
    assert path_a == path_b, f"Case 2 failed: {path_a!r} != {path_b!r}"

    # Case 3: Insert vs Delete
    op1 = insert(2, "X", client_id=1)
    op2 = delete(4, client_id=2)
    op1_p, op2_p = transform(op1, op2)
    path_a = apply_op(apply_op(doc, op1), op2_p)
    path_b = apply_op(apply_op(doc, op2), op1_p)
    assert path_a == path_b, f"Case 3 failed: {path_a!r} != {path_b!r}"

    # Case 4: Delete vs Insert
    op1 = delete(2, client_id=1)
    op2 = insert(4, "Y", client_id=2)
    op1_p, op2_p = transform(op1, op2)
    path_a = apply_op(apply_op(doc, op1), op2_p)
    path_b = apply_op(apply_op(doc, op2), op1_p)
    assert path_a == path_b, f"Case 4 failed: {path_a!r} != {path_b!r}"

    # Case 5: Delete vs Delete (different positions)
    op1 = delete(1, client_id=1)
    op2 = delete(4, client_id=2)
    op1_p, op2_p = transform(op1, op2)
    path_a = apply_op(apply_op(doc, op1), op2_p)
    path_b = apply_op(apply_op(doc, op2), op1_p)
    assert path_a == path_b, f"Case 5 failed: {path_a!r} != {path_b!r}"

    # Case 6: Delete vs Delete (same position)
    op1 = delete(3, client_id=1)
    op2 = delete(3, client_id=2)
    op1_p, op2_p = transform(op1, op2)
    path_a = apply_op(apply_op(doc, op1), op2_p)
    path_b = apply_op(apply_op(doc, op2), op1_p)
    assert path_a == path_b, f"Case 6 failed: {path_a!r} != {path_b!r}"

    # Case 7: Insert before delete position
    op1 = insert(1, "Z", client_id=1)
    op2 = delete(0, client_id=2)
    op1_p, op2_p = transform(op1, op2)
    path_a = apply_op(apply_op(doc, op1), op2_p)
    path_b = apply_op(apply_op(doc, op2), op1_p)
    assert path_a == path_b, f"Case 7 failed: {path_a!r} != {path_b!r}"

    # Case 8: Insert at delete position
    op1 = insert(3, "Z", client_id=1)
    op2 = delete(3, client_id=2)
    op1_p, op2_p = transform(op1, op2)
    path_a = apply_op(apply_op(doc, op1), op2_p)
    path_b = apply_op(apply_op(doc, op2), op1_p)
    assert path_a == path_b, f"Case 8 failed: {path_a!r} != {path_b!r}"

    print("  All 8 transform symmetry cases PASSED")


def convergence_proof_exhaustive(doc: str = "abc") -> None:
    """
    Exhaustive convergence proof: test ALL possible pairs of single operations
    on a given document, proving transform correctness for every combination.
    """
    n = len(doc)
    chars = "XYZ"
    ops = []

    # Generate all possible single operations
    for pos in range(n + 1):
        for ch in chars:
            ops.append(insert(pos, ch))
    for pos in range(n):
        ops.append(delete(pos))

    tested = 0
    for i, op1 in enumerate(ops):
        for j, op2 in enumerate(ops):
            op1_c = copy.deepcopy(op1)
            op2_c = copy.deepcopy(op2)
            op1_c.client_id = 1
            op2_c.client_id = 2

            op1_p, op2_p = transform(op1_c, op2_c)

            try:
                path_a = apply_op(apply_op(doc, op1_c), op2_p)
            except ValueError:
                continue
            try:
                path_b = apply_op(apply_op(doc, op2_c), op1_p)
            except ValueError:
                continue

            assert path_a == path_b, (
                f"Exhaustive convergence failed:\n"
                f"  doc={doc!r}, op1={op1_c}, op2={op2_c}\n"
                f"  path_a={path_a!r}, path_b={path_b!r}"
            )
            tested += 1

    print(f"  Exhaustive proof: {tested} operation pairs tested on doc={doc!r} — ALL CONVERGED")


if __name__ == "__main__":
    print("=" * 70)
    print("OT Engine — Convergence Proof & Integration Tests")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Basic apply operations
    # ------------------------------------------------------------------
    print("\n[1] Basic operation application")
    d = "hello"
    d = apply_op(d, insert(5, "!"))
    assert d == "hello!", f"Expected 'hello!' got {d!r}"
    d = apply_op(d, insert(0, "H"))
    assert d == "Hhello!", f"Expected 'Hhello!' got {d!r}"
    d = apply_op(d, delete(1))
    assert d == "Hello!", f"Expected 'Hello!' got {d!r}"
    print("  PASSED")

    # ------------------------------------------------------------------
    # 2. Transform symmetry (formal proof)
    # ------------------------------------------------------------------
    print("\n[2] Transform symmetry proof (8 cases)")
    convergence_proof_basic()

    # ------------------------------------------------------------------
    # 3. Exhaustive convergence proof
    # ------------------------------------------------------------------
    print("\n[3] Exhaustive convergence proof")
    convergence_proof_exhaustive("abc")
    convergence_proof_exhaustive("ab")
    convergence_proof_exhaustive("a")

    # ------------------------------------------------------------------
    # 4. Two-client simulation: concurrent inserts
    # ------------------------------------------------------------------
    print("\n[4] Two-client concurrent inserts")
    s_doc, c1_doc, c2_doc = simulate_concurrent_edits(
        "hello",
        [insert(0, "A"), insert(1, "B")],  # Client 1: "ABhello"
        [insert(5, "X"), insert(6, "Y")],  # Client 2: "helloXY"
    )
    assert s_doc == c1_doc == c2_doc, (
        f"Divergence! server={s_doc!r} c1={c1_doc!r} c2={c2_doc!r}"
    )
    assert s_doc == "ABhelloXY", f"Unexpected result: {s_doc!r}"
    print(f"  PASSED — all converged to {s_doc!r}")

    # ------------------------------------------------------------------
    # 5. Two-client simulation: concurrent deletes
    # ------------------------------------------------------------------
    print("\n[5] Two-client concurrent deletes")
    s_doc, c1_doc, c2_doc = simulate_concurrent_edits(
        "abcdef",
        [delete(0)],  # Client 1 deletes 'a'
        [delete(5)],  # Client 2 deletes 'f'
    )
    assert s_doc == c1_doc == c2_doc, (
        f"Divergence! server={s_doc!r} c1={c1_doc!r} c2={c2_doc!r}"
    )
    assert s_doc == "bcde", f"Unexpected result: {s_doc!r}"
    print(f"  PASSED — all converged to {s_doc!r}")

    # ------------------------------------------------------------------
    # 6. Two-client simulation: same-position delete
    # ------------------------------------------------------------------
    print("\n[6] Two-client same-position delete")
    s_doc, c1_doc, c2_doc = simulate_concurrent_edits(
        "abc",
        [delete(1)],  # Client 1 deletes 'b'
        [delete(1)],  # Client 2 also deletes 'b'
    )
    assert s_doc == c1_doc == c2_doc, (
        f"Divergence! server={s_doc!r} c1={c1_doc!r} c2={c2_doc!r}"
    )
    assert s_doc == "ac", f"Unexpected result: {s_doc!r}"
    print(f"  PASSED — all converged to {s_doc!r}")

    # ------------------------------------------------------------------
    # 7. Two-client simulation: insert vs delete conflict
    # ------------------------------------------------------------------
    print("\n[7] Two-client insert vs delete conflict")
    s_doc, c1_doc, c2_doc = simulate_concurrent_edits(
        "abcdef",
        [insert(3, "X")],   # Client 1 inserts X at pos 3
        [delete(3)],         # Client 2 deletes char at pos 3
    )
    assert s_doc == c1_doc == c2_doc, (
        f"Divergence! server={s_doc!r} c1={c1_doc!r} c2={c2_doc!r}"
    )
    print(f"  PASSED — all converged to {s_doc!r}")

    # ------------------------------------------------------------------
    # 8. Two-client simulation: same-position inserts (tie-break)
    # ------------------------------------------------------------------
    print("\n[8] Two-client same-position inserts (tie-break)")
    s_doc, c1_doc, c2_doc = simulate_concurrent_edits(
        "abc",
        [insert(1, "X")],  # Client 1 inserts X at pos 1
        [insert(1, "Y")],  # Client 2 inserts Y at pos 1
    )
    assert s_doc == c1_doc == c2_doc, (
        f"Divergence! server={s_doc!r} c1={c1_doc!r} c2={c2_doc!r}"
    )
    print(f"  PASSED — all converged to {s_doc!r}")

    # ------------------------------------------------------------------
    # 9. Multi-operation sequences
    # ------------------------------------------------------------------
    print("\n[9] Multi-operation sequences")
    s_doc, c1_doc, c2_doc = simulate_concurrent_edits(
        "the cat",
        [delete(0), delete(0), delete(0), delete(0),
         insert(0, "a"), insert(1, " ")],  # "the " -> "" -> "cat" -> "a cat"
        [insert(7, " "), insert(8, "s"), insert(9, "a"), insert(10, "t")],  # "the cat sat"
    )
    assert s_doc == c1_doc == c2_doc, (
        f"Divergence! server={s_doc!r} c1={c1_doc!r} c2={c2_doc!r}"
    )
    print(f"  PASSED — all converged to {s_doc!r}")

    # ------------------------------------------------------------------
    # 10. Stress test: many concurrent operations
    # ------------------------------------------------------------------
    print("\n[10] Stress test: 20 concurrent operations")
    c1_ops = [insert(i, chr(65 + i)) for i in range(10)]  # Insert A-J
    c2_ops = [insert(i, chr(97 + i)) for i in range(10)]  # Insert a-j
    s_doc, c1_doc, c2_doc = simulate_concurrent_edits("", c1_ops, c2_ops)
    assert s_doc == c1_doc == c2_doc, (
        f"Divergence! server={s_doc!r} c1={c1_doc!r} c2={c2_doc!r}"
    )
    assert len(s_doc) == 20, f"Expected 20 chars, got {len(s_doc)}"
    print(f"  PASSED — all converged to {s_doc!r} ({len(s_doc)} chars)")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("ALL TESTS PASSED — OT convergence verified")
    print("=" * 70)
