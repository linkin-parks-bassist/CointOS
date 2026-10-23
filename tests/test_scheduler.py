import unittest

from cointos import scheduler

CONFIG = {
    "classes": ["coin", "user", "background"],
    "reserved_lanes": [{"model": "front", "lane": 1, "classes": ["coin"]}],
    "scheduler": {"slice_seconds": 30},
}


def lane(model, index, holder=None, up=True, held_for=None, held_class=None, held_until=0):
    return {"model": model, "index": index, "up": up, "holder": holder,
            "held_for": held_for, "held_class": held_class, "held_until": held_until}


def waiting(id, klass, since, model="work", warm=(), agent=None):
    return {"id": id, "agent": agent or id, "class": klass, "model": model, "warm": list(warm), "lane": None,
            "since": None, "waiting_since": since, "reading": True}


def holding(id, klass, position, since, model="work", reading=False, agent=None):
    return {"id": id, "agent": agent or id, "class": klass, "model": model, "warm": [position], "lane": position,
            "since": since, "waiting_since": None, "reading": reading}


class Classes(unittest.TestCase):
    def test_higher_class_preempts_at_once(self):
        lanes = [lane("work", 0, holder="bg")]
        thoughts = [holding("bg", "background", 0, since=99), waiting("coin", "coin", since=100)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=100), {0: "coin"})

    def test_higher_class_displaces_a_generating_holder_before_a_reading_one(self):
        lanes = [lane("work", 0, holder="cold"), lane("work", 1, holder="warm")]
        thoughts = [holding("cold", "background", 0, since=90, reading=True), holding("warm", "background", 1, since=95),
                    waiting("coin", "coin", since=100)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=100), {0: "cold", 1: "coin"})

    def test_a_reading_holder_is_displaced_by_a_higher_class_when_there_is_no_other_lane(self):
        lanes = [lane("work", 0, holder="cold")]
        thoughts = [holding("cold", "background", 0, since=90, reading=True), waiting("coin", "coin", since=100)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=100), {0: "coin"})


class Slices(unittest.TestCase):
    def test_holder_keeps_lane_within_its_slice(self):
        lanes = [lane("work", 0, holder="a")]
        thoughts = [holding("a", "background", 0, since=90), waiting("b", "background", since=50)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=100), {0: "a"})

    def test_holder_past_its_slice_and_a_waiting_equal_draw_lots(self):
        lanes = [lane("work", 0, holder="a")]
        for now in range(100, 400, 30):
            thoughts = [holding("a", "background", 0, since=60), waiting("b", "background", since=95)]
            winner = max(thoughts, key=lambda t: scheduler.draw(CONFIG, t, now))["id"]
            self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=now), {0: winner})

    def test_a_reading_holder_is_not_preempted_by_an_equal(self):
        lanes = [lane("work", 0, holder="cold")]
        thoughts = [holding("cold", "background", 0, since=0, reading=True), waiting("b", "background", since=5)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=500), {0: "cold"})

    def test_checkpointed_reader_shares_expired_slices(self):
        lanes = [lane("work", 0, holder="cold")]
        for now in range(100, 400, 30):
            thoughts = [{**holding("cold", "background", 0, since=0, reading=True), "read_checkpoint": True},
                        waiting("b", "background", since=5)]
            winner = max(thoughts, key=lambda t: scheduler.draw(CONFIG, t, now))["id"]
            self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now), {0: winner})

    def test_holder_past_its_slice_keeps_lane_when_nobody_waits(self):
        lanes = [lane("work", 0, holder="a")]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [holding("a", "background", 0, since=0)], now=100), {0: "a"})

    def test_a_draw_holds_for_its_slot_and_is_redrawn_at_the_next(self):
        t = waiting("a", "background", since=0)
        self.assertEqual(scheduler.draw(CONFIG, t, 60), scheduler.draw(CONFIG, t, 89))
        self.assertNotEqual(scheduler.draw(CONFIG, t, 89), scheduler.draw(CONFIG, t, 90))

    def test_waiting_equals_win_slots_in_proportion_to_their_weight(self):
        wins = {"worker": 0, "gardener": 0}
        for n in range(4000):
            thoughts = [{**waiting("worker", "background", since=0), "weight": 4},
                        {**waiting("gardener", "background", since=0), "weight": 1}]
            wins[scheduler.assign(CONFIG, [lane("work", 0)], thoughts, now=n * 30)[0]] += 1
        self.assertAlmostEqual(wins["worker"] / 4000, 0.8, delta=0.03)

    def test_an_expired_holder_keeps_its_lane_in_proportion_to_its_weight(self):
        kept = 0
        for n in range(4000):
            thoughts = [{**holding("worker", "background", 0, since=n * 30 - 60), "weight": 4},
                        waiting("gardener", "background", since=0)]
            kept += scheduler.assign(CONFIG, [lane("work", 0, holder="worker")], thoughts, now=n * 30) == {0: "worker"}
        self.assertAlmostEqual(kept / 4000, 0.8, delta=0.03)

    def test_a_holder_inside_its_slice_is_not_in_the_draw(self):
        lanes = [lane("work", 0, holder="a"), lane("work", 1, holder="b")]
        for now in range(70, 75):
            thoughts = [holding("a", "background", 0, since=0), holding("b", "background", 1, since=now - 20),
                        waiting("c", "background", since=40)]
            winner = max(thoughts[0], thoughts[2], key=lambda t: scheduler.draw(CONFIG, t, now))["id"]
            self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=now), {0: winner, 1: "b"})

    def test_the_winner_displaces_the_holder_that_drew_lowest(self):
        lanes = [lane("work", 0, holder="a"), lane("work", 1, holder="b")]
        for now in range(300, 3000, 30):
            thoughts = [holding("a", "background", 0, since=0), holding("b", "background", 1, since=0),
                        waiting("c", "background", since=0)]
            loser = min(thoughts, key=lambda t: scheduler.draw(CONFIG, t, now))
            if loser["id"] == "c":
                continue
            wanted = scheduler.assign(CONFIG, lanes, thoughts, now=now)
            self.assertEqual(wanted[loser["lane"]], "c")
            self.assertEqual(sorted(wanted.values()), sorted(t["id"] for t in thoughts if t is not loser))


class Yielding(unittest.TestCase):
    def test_a_lane_kept_for_an_agent_is_not_given_to_an_equal(self):
        lanes = [lane("work", 0, held_for="a", held_class="background", held_until=110)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [waiting("b", "background", since=50)], now=100), {0: None})

    def test_the_agent_returns_to_the_lane_kept_for_it(self):
        lanes = [lane("work", 0), lane("work", 1, held_for="a", held_class="background", held_until=110)]
        thoughts = [waiting("b", "background", since=50), waiting("t", "background", since=99, agent="a")]
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=100), {0: "b", 1: "t"})

    def test_a_higher_class_may_take_a_kept_lane(self):
        lanes = [lane("work", 0, held_for="a", held_class="background", held_until=110)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [waiting("c", "coin", since=99)], now=100), {0: "c"})

    def test_the_grace_ends(self):
        lanes = [lane("work", 0, held_for="a", held_class="background", held_until=90)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [waiting("b", "background", since=50)], now=100), {0: "b"})


class Placement(unittest.TestCase):
    def test_a_thought_goes_to_the_lane_whose_state_begins_its_context(self):
        lanes = [lane("work", 0), lane("work", 1)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [waiting("t", "background", 5, warm=[1])], now=100),
                         {0: None, 1: "t"})

    def test_free_lane_before_displacing_anyone(self):
        lanes = [lane("work", 0, holder="a"), lane("work", 1)]
        thoughts = [holding("a", "background", 0, since=0), waiting("b", "background", since=95)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=100), {0: "a", 1: "b"})

    def test_reserved_lane_only_for_its_classes(self):
        lanes = [lane("front", 0, holder="x"), lane("front", 1)]
        thoughts = [holding("x", "user", 0, since=99, model="front"), waiting("u", "user", 1, model="front")]
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=100), {0: "x", 1: None})
        thoughts.append(waiting("c", "coin", 50, model="front"))
        self.assertEqual(scheduler.assign(CONFIG, lanes, thoughts, now=100), {0: "x", 1: "c"})

    def test_coin_takes_an_unreserved_lane_when_one_is_free(self):
        lanes = [lane("front", 0), lane("front", 1)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [waiting("c", "coin", 1, model="front")], now=100),
                         {0: "c", 1: None})

    def test_blocked_class_gets_no_lane(self):
        lanes = [lane("work", 0)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [waiting("bg", "background", 1)], now=100,
                                          blocked=frozenset({"background"})), {0: None})

    def test_down_lanes_are_not_used(self):
        lanes = [lane("work", 0, up=False), lane("work", 1)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [waiting("a", "background", 1)], now=100), {1: "a"})


if __name__ == "__main__":
    unittest.main()
