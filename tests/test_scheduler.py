import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eve_agent.scheduler import ScheduledTasks
from eve_agent.storage import EveDatabase


class ScheduledTasksTest(unittest.TestCase):
    def make_scheduler(self, root: Path) -> ScheduledTasks:
        scheduler = ScheduledTasks(EveDatabase(root / "data" / "eve.db"), start_monitor=False)
        scheduler.register_executor("eve_turn", lambda action: {
            "notification": {
                "message": f"ausgeführt: {action['request']}", "kind": "scheduled_result",
                "delivered": False, "conversation_id": action.get("conversation_id"),
                "task_id": action.get("task_id"),
            },
            "observed_action": action,
        })
        return scheduler

    @staticmethod
    def create(scheduler, request, schedule_type="once", schedule=None):
        if schedule is None:
            schedule = {"at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
        return scheduler.execute_operation("create", {
            "request": request, "name": request, "schedule_type": schedule_type,
            "schedule": schedule, "timezone": "Europe/Berlin",
        })

    @staticmethod
    def make_due(scheduler):
        with scheduler.database.connect() as connection:
            connection.execute(
                "UPDATE scheduled_tasks SET next_run_at=?",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
            )

    def test_native_contract_publishes_real_schema_and_current_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = self.make_scheduler(Path(tmp)).minimal_contract()
            create = contract["operations"]["create"]
            self.assertEqual("write", create["effect"])
            self.assertEqual(
                ["request", "schedule_type", "schedule"],
                create["parameters_schema"]["required"],
            )
            self.assertIn("delay", create["parameters_schema"]["properties"]["schedule_type"]["enum"])
            self.assertIn("current_time", contract)
            self.assertIn("local_timezone", contract)

    def test_once_task_executes_a_complete_eve_request_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            created = self.create(scheduler, "Rufe neue Nachrichten ab.")["result"]
            self.assertEqual("eve_turn", created["action"]["tool"])
            self.assertEqual("Rufe neue Nachrichten ab.", created["action"]["request"])
            self.make_due(scheduler)
            notifications = scheduler.pop_due()
            self.assertEqual("ausgeführt: Rufe neue Nachrichten ab.", notifications[0]["message"])
            self.assertEqual([], scheduler.pop_due())
            with scheduler.database.connect() as connection:
                self.assertEqual("completed", connection.execute("SELECT status FROM scheduled_tasks").fetchone()[0])
                self.assertEqual(1, connection.execute("SELECT count(*) FROM task_runs").fetchone()[0])

    def test_delay_is_one_shot_and_interval_repeats_without_completion_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            delayed = self.create(scheduler, "Einmal später", "delay", {"seconds": 600})["result"]
            self.create(scheduler, "Regelmäßig", "interval", {"seconds": 1800})
            self.assertGreater(datetime.fromisoformat(delayed["next_run_at"]), datetime.now(timezone.utc))
            scheduled_for = datetime.now(timezone.utc) - timedelta(seconds=1)
            with scheduler.database.connect() as connection:
                connection.execute("UPDATE scheduled_tasks SET next_run_at=?", (scheduled_for.isoformat(),))
            scheduler.pop_due()
            with scheduler.database.connect() as connection:
                rows = connection.execute(
                    "SELECT schedule_type,status,next_run_at FROM scheduled_tasks ORDER BY created_at"
                ).fetchall()
            self.assertEqual(("delay", "completed"), (rows[0]["schedule_type"], rows[0]["status"]))
            self.assertEqual("active", rows[1]["status"])
            self.assertGreater(datetime.fromisoformat(rows[1]["next_run_at"]), datetime.now(timezone.utc))

    def test_daily_and_weekly_schedules_are_structured_in_an_iana_timezone(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            self.create(scheduler, "Tageslauf", "daily", {"hour": 20, "minute": 0})
            self.create(scheduler, "Werktagslauf", "weekly", {
                "weekdays": [0, 1, 2, 3, 4], "hour": 8, "minute": 0,
            })
            with scheduler.database.connect() as connection:
                rows = connection.execute(
                    "SELECT schedule_type,schedule_json,timezone FROM scheduled_tasks ORDER BY created_at"
                ).fetchall()
            self.assertEqual(["daily", "weekly"], [row["schedule_type"] for row in rows])
            self.assertEqual("Europe/Berlin", rows[0]["timezone"])
            self.assertEqual([0, 1, 2, 3, 4], json.loads(rows[1]["schedule_json"])["weekdays"])

    def test_failed_recurring_occurrence_is_audited_and_next_occurrence_remains_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            self.create(scheduler, "Wiederholen", "interval", {"seconds": 60})
            scheduler.register_executor("eve_turn", lambda _action: (_ for _ in ()).throw(RuntimeError("offline")))
            self.make_due(scheduler)
            self.assertEqual([], scheduler.pop_due())
            with scheduler.database.connect() as connection:
                run = connection.execute("SELECT status,error_text FROM task_runs").fetchone()
                task = connection.execute("SELECT status,next_run_at FROM scheduled_tasks").fetchone()
            self.assertEqual("failed", run["status"])
            self.assertIn("offline", run["error_text"])
            self.assertEqual("active", task["status"])
            self.assertGreater(datetime.fromisoformat(task["next_run_at"]), datetime.now(timezone.utc))

    def test_tasks_can_be_listed_changed_paused_and_deleted_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            self.create(scheduler, "Alter Auftrag")
            task = scheduler.list_tasks()[0]
            changed = scheduler.update_task(task["id"], {
                "request": "Neuer Auftrag", "status": "paused",
                "schedule_type": "delay", "schedule": {"seconds": 7200},
            })
            self.assertEqual("paused", changed["status"])
            self.assertEqual("Neuer Auftrag", changed["action"]["request"])
            scheduler.delete_task(task["id"])
            self.assertEqual([], scheduler.list_tasks())
            with self.assertRaises(KeyError):
                scheduler.get_task(task["id"])

    def test_task_runs_are_inspectable_through_the_native_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            task = self.create(scheduler, "Prüfen")["result"]
            self.make_due(scheduler)
            scheduler.pop_due()
            result = scheduler.execute_operation("list_runs", {"task_id": task["id"], "limit": 10})
            self.assertEqual("succeeded", result["result"][0]["status"])
            self.assertEqual(task["id"], result["result"][0]["result"]["notification"]["task_id"])

    def test_task_update_rejects_past_dates_unknown_fields_and_unknown_timezone(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            task_id = self.create(scheduler, "Test")["result"]["id"]
            with self.assertRaisesRegex(ValueError, "Zukunft"):
                scheduler.update_task(task_id, {"next_run_at": "2000-01-01T00:00:00+00:00"})
            with self.assertRaisesRegex(ValueError, "Unbekanntes"):
                scheduler.update_task(task_id, {"executor": "shell"})
            with self.assertRaisesRegex(ValueError, "Zeitzone"):
                scheduler.update_task(task_id, {"timezone": "Mars/Olympus"})

    def test_no_second_language_model_normalization_is_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            scheduler = ScheduledTasks(
                EveDatabase(Path(tmp) / "data" / "eve.db"), start_monitor=False,
                title_normalizer=lambda source: calls.append(source),
            )
            scheduler.register_executor("eve_turn", lambda action: {"notification": {
                "message": action["request"], "delivered": False,
            }})
            self.create(scheduler, "Vom ursprünglichen Qwen-Turn formulierter Auftrag")
            self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
