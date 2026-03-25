import unittest


class InvalidTransition(Exception):
    pass


class StateMachine:
    def __init__(self, states, transitions, initial):
        if initial not in states:
            raise ValueError(f"Initial state '{initial}' not in states")
        self.states = set(states)
        self.transitions = {}
        for src, event, dst in transitions:
            if src not in self.states or dst not in self.states:
                raise ValueError(f"Transition references unknown state")
            self.transitions.setdefault(src, {})[event] = dst
        self.current = initial

    def transition(self, event):
        src_transitions = self.transitions.get(self.current, {})
        if event not in src_transitions:
            raise InvalidTransition(
                f"No transition for event '{event}' from state '{self.current}'"
            )
        self.current = src_transitions[event]
        return self.current


class TestTrafficLight(unittest.TestCase):
    def setUp(self):
        states = ["green", "yellow", "red"]
        transitions = [
            ("green", "timer", "yellow"),
            ("yellow", "timer", "red"),
            ("red", "timer", "green"),
        ]
        self.sm = StateMachine(states, transitions, "green")

    def test_initial_state(self):
        self.assertEqual(self.sm.current, "green")

    def test_green_to_yellow(self):
        self.assertEqual(self.sm.transition("timer"), "yellow")
        self.assertEqual(self.sm.current, "yellow")

    def test_yellow_to_red(self):
        self.sm.transition("timer")
        self.assertEqual(self.sm.transition("timer"), "red")

    def test_red_to_green(self):
        self.sm.transition("timer")
        self.sm.transition("timer")
        self.assertEqual(self.sm.transition("timer"), "green")

    def test_full_cycle(self):
        self.sm.transition("timer")
        self.sm.transition("timer")
        self.sm.transition("timer")
        self.assertEqual(self.sm.current, "green")

    def test_invalid_event(self):
        with self.assertRaises(InvalidTransition):
            self.sm.transition("push_button")

    def test_multiple_cycles(self):
        for _ in range(3):
            self.sm.transition("timer")
            self.sm.transition("timer")
            self.sm.transition("timer")
        self.assertEqual(self.sm.current, "green")


class TestDoorLock(unittest.TestCase):
    def setUp(self):
        states = ["locked", "unlocked", "open"]
        transitions = [
            ("locked", "unlock", "unlocked"),
            ("unlocked", "lock", "locked"),
            ("unlocked", "pull", "open"),
            ("open", "close", "unlocked"),
        ]
        self.sm = StateMachine(states, transitions, "locked")

    def test_initial_state(self):
        self.assertEqual(self.sm.current, "locked")

    def test_unlock(self):
        self.assertEqual(self.sm.transition("unlock"), "unlocked")

    def test_lock_after_unlock(self):
        self.sm.transition("unlock")
        self.assertEqual(self.sm.transition("lock"), "locked")

    def test_open_door(self):
        self.sm.transition("unlock")
        self.assertEqual(self.sm.transition("pull"), "open")

    def test_close_door(self):
        self.sm.transition("unlock")
        self.sm.transition("pull")
        self.assertEqual(self.sm.transition("close"), "unlocked")

    def test_cannot_open_locked_door(self):
        with self.assertRaises(InvalidTransition):
            self.sm.transition("pull")

    def test_cannot_lock_open_door(self):
        self.sm.transition("unlock")
        self.sm.transition("pull")
        with self.assertRaises(InvalidTransition):
            self.sm.transition("lock")

    def test_cannot_unlock_open_door(self):
        self.sm.transition("unlock")
        self.sm.transition("pull")
        with self.assertRaises(InvalidTransition):
            self.sm.transition("unlock")

    def test_cannot_pull_locked(self):
        with self.assertRaises(InvalidTransition):
            self.sm.transition("pull")

    def test_full_sequence_lock_unlock_open_close_lock(self):
        self.sm.transition("unlock")
        self.sm.transition("pull")
        self.sm.transition("close")
        self.sm.transition("lock")
        self.assertEqual(self.sm.current, "locked")


class TestStateMachineEdgeCases(unittest.TestCase):
    def test_invalid_initial_state(self):
        with self.assertRaises(ValueError):
            StateMachine(["a", "b"], [], "c")

    def test_transition_references_unknown_state(self):
        with self.assertRaises(ValueError):
            StateMachine(["a"], [("a", "go", "b")], "a")

    def test_single_state_no_transitions(self):
        sm = StateMachine(["only"], [], "only")
        self.assertEqual(sm.current, "only")
        with self.assertRaises(InvalidTransition):
            sm.transition("anything")

    def test_self_transition(self):
        sm = StateMachine(["idle"], [("idle", "noop", "idle")], "idle")
        sm.transition("noop")
        self.assertEqual(sm.current, "idle")


if __name__ == "__main__":
    # Run assertions manually
    # Traffic light
    sm = StateMachine(["green", "yellow", "red"], [
        ("green", "timer", "yellow"),
        ("yellow", "timer", "red"),
        ("red", "timer", "green"),
    ], "green")
    assert sm.current == "green"
    assert sm.transition("timer") == "yellow"
    assert sm.transition("timer") == "red"
    assert sm.transition("timer") == "green"
    try:
        sm.transition("push_button")
        assert False, "Should have raised InvalidTransition"
    except InvalidTransition:
        pass

    # Door lock
    door = StateMachine(["locked", "unlocked", "open"], [
        ("locked", "unlock", "unlocked"),
        ("unlocked", "lock", "locked"),
        ("unlocked", "pull", "open"),
        ("open", "close", "unlocked"),
    ], "locked")
    assert door.current == "locked"
    assert door.transition("unlock") == "unlocked"
    assert door.transition("pull") == "open"
    assert door.transition("close") == "unlocked"
    assert door.transition("lock") == "locked"
    try:
        door.transition("pull")
        assert False, "Should have raised InvalidTransition"
    except InvalidTransition:
        pass

    # Edge cases
    try:
        StateMachine(["a"], [], "z")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    sm2 = StateMachine(["idle"], [("idle", "noop", "idle")], "idle")
    assert sm2.transition("noop") == "idle"

    print("All assertions passed.")

    # Also run unittest suite
    unittest.main()
