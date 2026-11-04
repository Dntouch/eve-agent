import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from eve_agent.scheduler import ScheduledTasks
from eve_agent.storage import EveDatabase


class ScheduledTasksTest(unittest.TestCase):
    def test_task_paused_after_due_list_was_read_is_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            first = self.create(scheduler, 'Erster Check')['result']
            second = self.create(scheduler, 'Zweiter Check')['result']
            now = datetime.now(timezone.utc)
            with scheduler.database.connect() as c:
                for task, seconds in ((first, 2), (second, 1)):
                    c.execute('UPDATE scheduled_tasks SET next_run_at=? WHERE id=?',
                              ((now - timedelta(seconds=seconds)).isoformat(), task['id']))
            executed = []
            def execute(action):
                executed.append(action['task_id'])
                scheduler.update_task(second['id'], {'status': 'paused'})
                return {'outcome': 'no_change', 'reason': 'Keine Änderung'}
            scheduler.register_executor('eve_turn', execute)
            scheduler.pop_due()
            self.assertEqual([first['id']], executed)
            self.assertEqual('paused', scheduler.get_task(second['id'])['status'])

    def test_end_date_roundtrip_edit_and_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
            task = self.create(scheduler, 'Erinnere jetzt', 'interval', {'seconds': 60, 'ends_at': end})['result']
            self.assertEqual(task['schedule']['ends_at'], end)
            restored = ScheduledTasks(scheduler.database, start_monitor=False)
            self.assertEqual(restored.get_task(task['id'])['schedule']['ends_at'], end)
            updated = scheduler.update_task(task['id'], {'schedule_type': 'daily',
                'schedule': {'hour': 9, 'minute': 0, 'ends_at': end}})
            self.assertEqual(updated['schedule']['ends_at'], end)
            updated = scheduler.update_task(task['id'], {'schedule_type': 'daily',
                'schedule': {'hour': 9, 'minute': 0, 'ends_at': None}})
            self.assertNotIn('ends_at', updated['schedule'])

    def test_invalid_end_dates_and_first_run_after_end_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            for end in ('', 'not-a-date', 42, (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()):
                with self.subTest(end=end), self.assertRaises(ValueError):
                    self.create(scheduler, 'Erinnere', 'interval', {'seconds': 3600, 'ends_at': end})
            task = self.create(scheduler, 'Erinnere', 'interval', {'seconds': 60,
                'ends_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})['result']
            with self.assertRaisesRegex(ValueError, 'Enddatum'):
                scheduler.update_task(task['id'], {'next_run_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})

    def test_expired_overdue_task_is_completed_without_execution_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            task = self.create(scheduler, 'Erinnere', 'interval', {'seconds': 60})['result']
            end = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            with scheduler.database.connect() as c:
                c.execute('UPDATE scheduled_tasks SET schedule_json=?,next_run_at=? WHERE id=?',
                          (json.dumps({'seconds': 60, 'ends_at': end}), end, task['id']))
            restarted = ScheduledTasks(scheduler.database, start_monitor=False)
            execute = Mock()
            restarted.register_executor('eve_turn', execute)
            self.assertEqual(restarted.pop_due(), [])
            execute.assert_not_called()
            self.assertEqual(restarted.get_task(task['id'])['status'], 'completed')
            self.assertIsNone(restarted.get_task(task['id'])['next_run_at'])
            with scheduler.database.connect() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM task_runs').fetchone()[0], 0)

    def test_end_boundary_is_inclusive_for_all_recurring_types_and_dst(self):
        finished = datetime.fromisoformat('2026-10-24T08:00:00+00:00')
        end = '2026-10-25T08:00:00+00:00'  # 09:00 Berlin after DST change
        for kind, timing in [('daily', {'hour': 9, 'minute': 0}),
                             ('weekly', {'hour': 9, 'minute': 0, 'weekdays': [6]}),
                             ('interval', {'seconds': 86400})]:
            schedule = {**timing, 'ends_at': end}
            candidate = ScheduledTasks._next_after(kind, schedule, finished, finished, 'Europe/Berlin')
            self.assertEqual(candidate, datetime.fromisoformat(end))
            self.assertIsNone(ScheduledTasks._next_after(kind, schedule, candidate, candidate, 'Europe/Berlin'))
        timing = ScheduledTasks._validate_schedule('daily', {'hour': 9, 'minute': 0,
            'ends_at': '2026-10-25T09:00:00'}, 'Europe/Berlin')
        self.assertEqual(timing['ends_at'], end)

    def test_last_run_finishes_task_and_edits_during_run_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            task = self.create(scheduler, 'Erinnere', 'interval', {'seconds': 3600,
                'ends_at': (datetime.now(timezone.utc) + timedelta(seconds=3700)).isoformat()})['result']
            self.make_due(scheduler)
            def execute(action):
                scheduler.update_task(task['id'], {'status': 'paused'})
                return {'notification': {'message': 'Erinnerung', 'delivered': False}}
            scheduler.register_executor('eve_turn', execute)
            scheduler.pop_due()
            self.assertEqual(scheduler.get_task(task['id'])['status'], 'paused')
            scheduler.update_task(task['id'], {'status': 'active'})
            with scheduler.database.connect() as c:
                c.execute('UPDATE scheduled_tasks SET schedule_json=? WHERE id=?',
                          (json.dumps({'seconds': 3600, 'ends_at': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}), task['id']))
            scheduler.register_executor('eve_turn', lambda action: {'notification': {'message': 'Letzte', 'delivered': False}})
            self.make_due(scheduler)
            self.assertEqual(scheduler.pop_due()[0]['message'], 'Letzte')
            final = scheduler.get_task(task['id'])
            self.assertEqual(final['status'], 'completed')
            self.assertIsNone(final['next_run_at'])

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

    def test_tool_schemas_do_not_grow_with_destination_and_task_inventories(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self.make_scheduler(Path(tmp))
            original = scheduler.minimal_contract()["operations"]
            targets = [{"id": f"eve:conversation:{i:032x}", "name": f"Chat {i}",
                        "transport": "eve", "conversation_id": f"{i:032x}"}
                       for i in range(1000)]
            scheduler.output_targets_provider = Mock(return_value=targets)
            self.create(scheduler, "Testauftrag")
            contract = scheduler.minimal_contract()
            self.assertEqual(original, contract["operations"])
            scheduler.output_targets_provider.assert_not_called()
            self.assertEqual(1001, len(scheduler.execute_operation("list_output_targets", {})["result"]))
            scheduler.output_targets_provider.assert_called_once_with()

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
