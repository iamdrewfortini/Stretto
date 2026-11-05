# SPDX-License-Identifier: Apache-2.0
"""Calendar and Goals backend: sessions, task scheduling fields, weekly goal and category budgets, the goals aggregate."""
import datetime as dt, http.client, json, os, shutil, sqlite3, tempfile, threading, unittest, urllib.parse

from stretto import daycache, demo
from stretto.server import make_server
from stretto.store import Store

TODAY = dt.date.today()


def day0(k):
    return dt.datetime.combine(TODAY - dt.timedelta(days=k), dt.time()).timestamp()


def iso(k):
    return (TODAY - dt.timedelta(days=k)).isoformat()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "t.sqlite")
        cls.store = Store(cls.path)
        cls.srv, cls.tok = make_server(cls.store, 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, method, path, body=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json"}
        if token:
            h["X-Stretto-Token"] = self.tok
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        return r.status, data

    def main_only(self, sql, args=()):
        d = tempfile.mkdtemp()
        dst = os.path.join(d, "m.sqlite")
        shutil.copy(self.path, dst)
        c = sqlite3.connect(dst)
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()


class Sessions(Base):
    def add(self, start, end, label="x", kind="focus", task_id=None):
        return self.store.x("INSERT INTO timers(task_id,label,kind,start,end) VALUES(?,?,?,?,?)", (task_id, label, kind, start, end))

    def get(self, f, t):
        return self.call("GET", f"/api/sessions?from={f}&to={t}")

    def test_shape_order_task_title_and_running_session(self):
        _, t = self.call("POST", "/api/tasks", dict(title="Write plan"))
        a, b = day0(20) + 9 * 3600, day0(20) + 10 * 3600
        self.add(b, b + 600, "second", "break")
        self.add(a, a + 1500, "first", "focus", task_id=t["id"])
        self.add(b + 3600, None, "running", "focus")
        code, r = self.get(iso(20), iso(20))
        self.assertEqual(code, 200)
        ss = r["sessions"]
        self.assertEqual([s["label"] for s in ss], ["first", "second", "running"])                 # ordered by start
        self.assertEqual(set(ss[0]), {"id", "task_id", "label", "kind", "start", "end", "task_title"})
        self.assertEqual((ss[0]["task_title"], ss[1]["task_title"]), ("Write plan", None))         # joined; null when there is no task
        self.assertEqual((ss[1]["kind"], ss[2]["end"]), ("break", None))                           # end is null while running

    def test_a_session_across_midnight_appears_on_both_days_and_the_range_is_inclusive(self):
        s, e = day0(30) + 23 * 3600 + 1800, day0(29) + 1800
        sid = self.add(s, e, "late")
        for d in (iso(30), iso(29)):
            self.assertIn(sid, [x["id"] for x in self.get(d, d)[1]["sessions"]], d)
        self.assertNotIn(sid, [x["id"] for x in self.get(iso(31), iso(31))[1]["sessions"]])
        self.assertIn(sid, [x["id"] for x in self.get(iso(31), iso(29))[1]["sessions"]])

    def test_bad_ranges_are_400_not_500(self):
        for q in ("", f"from={iso(5)}", f"from={iso(1)}&to={iso(5)}", "from=2026-13-01&to=2026-13-02", "from=20261104&to=20261105",
                  f"from={iso(100)}&to={iso(0)}"):
            code, r = self.call("GET", "/api/sessions?" + q)
            self.assertEqual(code, 400, q)
            self.assertIn("error", r)
        self.assertEqual(self.get(iso(61), iso(0))[0], 200)                                         # exactly 62 days is allowed
        self.assertEqual(self.get(iso(62), iso(0))[0], 400)                                         # 63 is not

    def test_timer_kind_is_focus_or_break_only(self):
        self.assertEqual(self.call("POST", "/api/timer/start", dict(kind="break"))[0], 200)
        self.assertEqual(self.call("POST", "/api/timer/start", dict(kind="nap"))[0], 400)
        self.assertEqual(self.call("POST", "/api/timer/start", dict(label="no kind given"))[0], 200)  # default stays focus
        self.call("POST", "/api/timer/stop")


class TaskScheduling(Base):
    def task(self, **kw):
        return self.call("POST", "/api/tasks", dict(title="T", **kw))

    def row(self, tid):
        return [t for t in self.call("GET", "/api/tasks")[1] if t["id"] == tid][0]

    def test_create_and_update_planned_start_and_due(self):
        ps = day0(1) + 14 * 3600
        code, r = self.task(planned_start=ps, due=iso(-2))
        self.assertEqual(code, 200)
        t = self.row(r["id"])
        self.assertEqual((t["planned_start"], t["due"]), (ps, iso(-2)))
        self.assertEqual(self.call("POST", f"/api/tasks/{r['id']}", dict(planned_start=ps + 3600))[0], 200)       # drag to another hour
        t = self.row(r["id"])
        self.assertEqual((t["planned_start"], t["due"]), (ps + 3600, iso(-2)))                                    # due left alone: absent means untouched
        self.call("POST", f"/api/tasks/{r['id']}", dict(planned_start=None, due=None))
        t = self.row(r["id"])
        self.assertEqual((t["planned_start"], t["due"]), (None, None))                                            # present and null clears

    def test_status_still_works_and_combines_with_the_new_fields_in_one_write(self):
        _, r = self.task()
        self.call("POST", f"/api/tasks/{r['id']}", dict(status="done", due=iso(0)))
        t = self.row(r["id"])
        self.assertEqual((t["status"], t["due"]), ("done", iso(0)))
        self.assertIsNotNone(t["done_at"])

    def test_bad_values_are_400_and_change_nothing(self):
        _, r = self.task(due=iso(3))
        before = self.row(r["id"])
        for bad in (dict(due="tomorrow"), dict(due="2026-13-40"), dict(due="20261104"), dict(due=5), dict(planned_start="noon"),
                    dict(planned_start=5), dict(planned_start=True), dict(planned_start=9e12), dict(status="nope", due=iso(0))):
            self.assertEqual(self.call("POST", f"/api/tasks/{r['id']}", bad)[0], 400, bad)
        self.assertEqual(self.row(r["id"]), before)                                                               # a failed request wrote nothing
        self.assertEqual(self.task(due="soon")[0], 400)
        self.assertEqual(self.task(planned_start="x")[0], 400)

    def test_unknown_task_is_404_and_the_write_reaches_the_main_file(self):
        self.assertEqual(self.call("POST", "/api/tasks/999999", dict(due=iso(0)))[0], 404)
        _, r = self.task()
        ps = day0(2) + 9 * 3600
        self.call("POST", f"/api/tasks/{r['id']}", dict(planned_start=ps))
        self.assertEqual(self.main_only("SELECT planned_start FROM tasks WHERE id=?", (r["id"],)), [(ps,)])      # a person's scheduling is durable at once

    def test_token_rules_apply(self):
        self.assertEqual(self.call("POST", "/api/tasks", dict(title="x"), token=False)[0], 403)


class Settings(Base):
    def setUp(self):
        self.store.x("DELETE FROM settings")                          # every test starts from a clean slate: the server and database are shared
        self.store.x("DELETE FROM rules")

    def test_defaults_and_goal_min_unchanged(self):
        code, s = self.call("GET", "/api/settings")
        self.assertEqual(code, 200)
        self.assertEqual(s["goal_min"], 240)
        self.assertEqual((s["goal_week_min"], s["budgets"]), (1200, {}))                           # default is 5 x goal_min; no budgets
        self.assertEqual(self.call("POST", "/api/settings", dict(goal_min=60))[1]["goal_week_min"], 300)
        self.call("POST", "/api/settings", dict(goal_min=240))

    def test_weekly_goal_validation_and_the_two_fields_are_independent(self):
        self.assertEqual(self.call("POST", "/api/settings", dict(goal_week_min=600))[1]["goal_week_min"], 600)
        self.assertEqual(self.call("GET", "/api/settings")[1]["goal_min"], 240)                    # untouched
        for bad in (59, 4801, "lots", 12.5, True, None, [1]):
            self.assertEqual(self.call("POST", "/api/settings", dict(goal_week_min=bad))[0], 400, bad)
        self.assertEqual(self.call("POST", "/api/settings", {})[0], 400)                           # nothing to change is an error, not a silent ok
        self.assertEqual(self.call("POST", "/api/settings", dict(goal_week_min="900"))[1]["goal_week_min"], 900)
        self.assertEqual(self.call("POST", "/api/settings", dict(goal_week_min=60))[0], 200)       # bounds are inclusive
        self.assertEqual(self.call("POST", "/api/settings", dict(goal_week_min=4800))[0], 200)

    def test_budgets_are_validated_replaced_and_durable(self):
        code, s = self.call("POST", "/api/settings", dict(budgets={"Distraction": 30, "Build": 960}))
        self.assertEqual((code, s["budgets"]), (200, {"Distraction": 30, "Build": 960}))
        self.assertEqual(self.call("POST", "/api/settings", dict(budgets={"Learn": 0}))[1]["budgets"], {"Learn": 0})   # replaces: Distraction is gone
        self.assertEqual(self.main_only("SELECT v FROM settings WHERE k='budgets'"), [('{"Learn": 0}',)])             # durable at once
        for bad in ({"Gaming": 10}, {"Idle": 10}, {"Build": -1}, {"Build": 961}, {"Build": "x"}, {"Build": 1.5}, {"Build": True}, ["Build"], "Build"):
            self.assertEqual(self.call("POST", "/api/settings", dict(budgets=bad))[0], 400, bad)
        self.assertEqual(self.call("GET", "/api/settings")[1]["budgets"], {"Learn": 0})            # failures changed nothing
        self.assertEqual(self.call("POST", "/api/settings", dict(budgets={}))[1]["budgets"], {})   # empty clears all

    def test_a_category_from_the_persons_own_rule_may_be_budgeted(self):
        self.assertEqual(self.call("POST", "/api/settings", dict(budgets={"Client work": 120}))[0], 400)
        self.call("POST", "/api/rules", dict(field="app", pattern="^figma$", category="Client work"))
        self.assertEqual(self.call("POST", "/api/settings", dict(budgets={"Client work": 120}))[0], 200)

    def test_a_bad_field_alongside_a_good_one_changes_neither(self):
        self.call("POST", "/api/settings", dict(goal_week_min=700, budgets={}))
        self.assertEqual(self.call("POST", "/api/settings", dict(goal_week_min=800, budgets={"Nope": 1}))[0], 400)
        self.assertEqual(self.call("GET", "/api/settings")[1]["goal_week_min"], 700)


class Goals(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for k in range(1, 8):
            cls.store.ingest(demo.samples(day0(k), seed=k), "collector", "d")

    def test_range_days_carry_by_category_matching_the_day_view(self):
        r = self.call("GET", "/api/range?days=7")[1]
        for d in r["days"]:
            if d["total_s"]:
                self.assertEqual(d["by_category"], self.call("GET", f"/api/day?date={d['date']}")[1]["summary"]["by_category"], d["date"])

    def test_goals_aggregate_equals_the_sum_of_its_days_and_carries_the_weekly_goal(self):
        self.call("POST", "/api/settings", dict(goal_week_min=900, budgets={"Distraction": 45}))
        code, g = self.call("GET", "/api/goals?days=7")
        self.assertEqual(code, 200)
        rng = self.call("GET", "/api/range?days=7")[1]
        self.assertEqual(g["days"], rng["days"])
        self.assertEqual(g["week"]["focus_s"], sum(d["focus_s"] for d in rng["days"]))
        self.assertEqual(g["week"]["total_s"], sum(d["total_s"] for d in rng["days"]))
        self.assertEqual(g["week"]["goal_week_s"], 900 * 60)
        for cat, secs in g["week"]["by_category"].items():
            self.assertEqual(secs, sum(d["by_category"].get(cat, 0) for d in rng["days"]), cat)
        self.assertEqual((g["budgets"], g["goal_s"]), ({"Distraction": 45}, rng["goal_s"]))

    def test_days_parameter_is_clamped_and_bad_input_is_400(self):
        self.assertEqual(len(self.call("GET", "/api/goals?days=1")[1]["days"]), 1)
        self.assertEqual(len(self.call("GET", "/api/goals?days=500")[1]["days"]), 90)
        self.assertEqual(self.call("GET", "/api/goals?days=abc")[0], 400)


if __name__ == "__main__":
    unittest.main()
