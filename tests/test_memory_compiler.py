import json
import sqlite3
import threading
import time
import tempfile
import unittest
from pathlib import Path

from eve_agent.memory_compiler import MemoryCompiler, MemoryNeed, _Candidate, _fts_query_tokens
from eve_agent.storage import EveDatabase, SCHEMA_VERSION


class MemoryCompilerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = EveDatabase(Path(self.temp.name) / "eve.db")
        with self.database.connect() as c:
            c.execute("INSERT INTO conversations(id,title,created_at,updated_at) VALUES ('c','x','2026','2026')")
            c.execute("""INSERT INTO messages(id,conversation_id,role,content,ordinal,created_at)
                         VALUES ('u','c','user','Welches Rollo ist im Wohnzimmer? ',0,'2026')""")
            c.execute("""INSERT INTO messages(id,conversation_id,role,content,ordinal,created_at)
                         VALUES ('a','c','assistant','Antwort',1,'2026')""")
            c.execute("""INSERT INTO turns(id,conversation_id,user_message_id,assistant_message_id,
                         knowledge_flow_json,created_at,completed_at) VALUES
                         ('t','c','u','a','{}','2026','2026')""")
        self.compiler = MemoryCompiler(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def claim(self, identifier, text, *, lifecycle="active", scope="legacy:global",
              slot="room:living:cover", kind="opaque_fact", payload=None, valid_until=None):
        with self.database.connect() as c:
            c.execute("""INSERT INTO memory_claims
                (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,
                 valid_until,verification_policy,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,'configuration','2025','2025')""",
                (identifier, kind, scope, "key:" + identifier, slot, text,
                 json.dumps(payload or {}), lifecycle, valid_until))

    def need(self, consumer="answer", **changes):
        values = dict(consumer=consumer, query="Rollo Wohnzimmer",
                      scopes=("legacy:global",), provider=None)
        values.update(changes)
        return MemoryNeed(**values)

    def test_fts_recall_consumer_isolation_and_idempotency(self):
        self.claim("x", "Das Rollo im Wohnzimmer heißt Sonnenblende")
        answer = self.compiler.compile_turn("t", "answer", need=self.need())
        planner = self.compiler.compile_turn("t", "planner", need=self.need("planner"))
        repeated = self.compiler.compile_turn("t", "answer", need=self.need())
        self.assertEqual("would_present", answer["status"])
        self.assertIn("Sonnenblende", answer["rendered_view"])
        self.assertNotEqual(answer["id"], planner["id"])
        self.assertEqual(answer["id"], repeated["id"])
        with self.database.connect() as c:
            self.assertEqual(2, c.execute("SELECT count(*) FROM memory_compiler_evaluations").fetchone()[0])

    def test_complete_display_match_survives_long_statement(self):
        self.claim("invitation", (
            "Mira ist unabhängig von Tarek zu unserem regelmäßigen Lesetermin eingeladen. "
            "Dieser Lesetermin findet jede Woche dienstags um 10 Uhr statt."
        ), slot=None)
        view = self.compiler.compile_turn(
            "t", "answer", need=self.need(query="Mira Lesetermin"),
        )
        self.assertIn("Mira ist unabhängig von Tarek", view["rendered_view"])

    def test_word_prefix_collision_does_not_create_device_anchor(self):
        self.claim("invitation", (
            "Mira ist unabhängig von Tarek zu unserem regelmäßigen Lesetermin eingeladen. "
            "Dieser Lesetermin findet jede Woche dienstags um 10 Uhr statt."
        ), slot=None)
        self.claim("kiosk", "Kiosk Eingesteckt", kind="provider_binding", slot=None, payload={
            "provider": "home_assistant", "subject": "Kiosk Eingesteckt",
            "property": "resource", "external_reference": "binary_sensor.kiosk_eingesteckt",
        })
        view = self.compiler.compile_turn(
            "t", "answer", need=self.need(query="Mira regelmäßigen Lesetermin eingeladen"),
        )
        self.assertIn("Mira ist unabhängig von Tarek", view["rendered_view"])
        self.assertNotIn("Kiosk Eingesteckt", view["rendered_view"])
        self.assertFalse(self.compiler._token_matches("eingeladen", "eingesteckt"))
        exact = self.compiler.compile_turn(
            "t", "planner", need=self.need("planner", query="Kiosk Eingesteckt", provider="home_assistant"),
        )
        self.assertIn("Kiosk Eingesteckt", exact["rendered_view"])

    def test_partial_device_name_does_not_override_general_fact_query(self):
        self.claim("correction", "Mira und Tarek arbeiten nicht zusammen. Die frühere Meldung war falsch.", slot=None)
        self.claim("notification", "Abwesenheit Aktiv Meldung", kind="provider_binding", slot=None, payload={
            "provider": "home_assistant", "subject": "Abwesenheit Aktiv Meldung",
            "property": "resource", "external_reference": "automation.abwesenheit_aktiv_meldung",
        })
        view = self.compiler.compile_turn(
            "t", "answer", need=self.need(query="Mira Tarek frühere Meldung"),
        )
        self.assertIn("Mira und Tarek arbeiten nicht zusammen", view["rendered_view"])
        exact = self.compiler.compile_turn(
            "t", "planner", need=self.need("planner", query="Abwesenheit Aktiv Meldung", provider="home_assistant"),
        )
        self.assertIn("Abwesenheit Aktiv Meldung", exact["rendered_view"])

    def test_exact_device_name_does_not_hide_general_integration_fact(self):
        self.claim("integration", (
            "Mittlerweile haben wir Dich als Assistant in Home Assistant eingebunden. "
            "Über eine richtige Integration. Mittels HACS."
        ), slot=None)
        self.claim("device", "Home Assistant", kind="provider_binding", slot=None, payload={
            "provider": "home_assistant", "subject": "Home Assistant",
            "property": "resource", "external_reference": "conversation.home_assistant",
        })
        view = self.compiler.compile_turn(
            "t", "answer", need=self.need(query="Home Assistant HACS"),
        )
        self.assertIn("Mittels HACS", view["rendered_view"])
        # Explicit provider requests still require the resource's subject.
        self.claim("neighbour", "HACS hat einen Event-Channel", slot=None)
        provider_view = self.compiler.compile_turn(
            "t", "answer", need=self.need(query="Home Assistant HACS", provider="home_assistant"),
        )
        self.assertNotIn("Event-Channel", provider_view["rendered_view"])

    def test_single_term_keeps_multiple_mentions_without_identity_inference(self):
        self.claim("one", "Mira sprach über japanische Tattoos.", slot=None)
        self.claim("two", "Mira berichtete über einen Lesetermin.", slot=None)
        self.claim("other", "Tarek sprach über ein Buch.", slot=None)
        view = self.compiler.compile_turn(
            "t", "answer", need=self.need(query="Mira"),
        )
        self.assertIn("japanische Tattoos", view["rendered_view"])
        self.assertIn("Lesetermin", view["rendered_view"])
        self.assertNotIn("Tarek", view["rendered_view"])

    def test_long_partial_match_keeps_coverage_guard(self):
        claim = {
            "id": "calendar", "claim_kind": "opaque_fact", "scope": "legacy:global",
            "canonical_key": "calendar_profile", "slot_key": None, "payload_json": "{}",
            "display_text": (
                "Wann findet eine Veranstaltung statt? Dieses Kalenderprofil erläutert "
                "verschiedene Funktionen für Erinnerungen, Termine und allgemeine "
                "Planung sowie weitere Möglichkeiten zur Verwaltung eines Kalenders."
            ),
        }
        reason = self.compiler._positive_relevance(
            _Candidate(claim), self.need(query="Wann findet Miras Lesetermin statt?"), [],
        )
        self.assertIsNone(reason)

    def test_long_fts_query_keeps_informative_terms_from_original_word_order(self):
        query = (
            "Bitte beschreibe ausführlich und verständlich, was das Projekt kann und wie man "
            "damit arbeitet. Berücksichtige dabei versteckte Funktionen, gespeicherte Messwerte, "
            "Serverprotokolle und Wartungsintervalle."
        )
        terms = _fts_query_tokens(query)
        selected = terms[:12]

        self.assertLessEqual(len(selected), 12)
        self.assertIn("funktionen", selected)
        self.assertIn("messwerte", selected)
        self.assertIn("serverprotokolle", selected)
        self.assertIn("wartungsintervalle", selected)
        self.assertLess(selected.index("wartungsintervalle"), selected.index("beschreibe"))
        self.assertEqual(terms, _fts_query_tokens(query))

    def test_self_description_shape_is_not_alphabetically_truncated(self):
        query = (
            "Beschreibe EVE ausführlich aus Sicht eines Benutzers. Erkläre, was EVE ist, "
            "welche Funktionen und Möglichkeiten sie besitzt, wie man mit ihr arbeiten kann "
            "und was sie von einem einfachen Chatbot unterscheidet. Berücksichtige dabei auch "
            "Funktionen, die nicht ständig sichtbar sind, aber zum System gehören. Strukturiere "
            "die Beschreibung sinnvoll und verständlich. Nutze dein vorhandenes Wissen über "
            "dich selbst und deine tatsächlich verfügbaren Möglichkeiten. Erfinde keine "
            "Funktionen, die dir nicht zur Verfügung stehen."
        )

        selected = _fts_query_tokens(query)[:12]

        self.assertEqual(
            ["berücksichtige", "möglichkeiten", "unterscheidet", "strukturiere",
             "beschreibung", "verständlich", "ausführlich", "vorhandenes",
             "tatsächlich", "verfügbaren", "beschreibe", "funktionen"],
            selected,
        )
        self.assertNotEqual(sorted(selected), selected)

    def test_short_fts_query_and_prefix_expression_remain_stable(self):
        terms = _fts_query_tokens("Wie heißt mein Tesla?")
        self.assertEqual(["heisst", "tesla", "mein", "wie"], terms)
        self.assertEqual(
            '"heisst" OR "heis"* OR "tesla" OR "mein" OR "wie"',
            self.compiler._fts_expression(terms),
        )
        self.assertIn('"wart"*', self.compiler._fts_expression(["wartungsintervalle"]))

    def test_coverage_orders_distinct_relevant_aspects_before_near_duplicates(self):
        def candidate(identifier, text, score):
            return _Candidate({
                "id": identifier, "scope": "legacy:global", "claim_kind": "opaque_fact",
                "canonical_key": f"fact:{identifier}", "slot_key": None,
                "display_text": text, "payload_json": "{}", "lifecycle": "active",
            }, score=score, requirement="useful")

        items = [
            candidate("a1", "Apfelernte im Nordgarten beginnt im September", 4.10),
            candidate("a2", "Apfelernte im Nordgarten startet Anfang September", 4.09),
            candidate("a3", "Die Äpfel im Nordgarten werden im September geerntet", 4.08),
            candidate("b", "Die Solaranlage speist einen Batteriespeicher", 4.07),
            candidate("c", "Der Bachlauf versorgt den Bewässerungsteich", 4.06),
            candidate("d", "Werkzeuge lagern im südlichen Geräteschuppen", 4.05),
        ]

        ordered = self.compiler._coverage_order(
            items, self.need(query="Gib mir einen Überblick über Garten und Grundstück"),
        )

        identifiers = [item.claim["id"] for item in ordered]
        self.assertEqual("a1", identifiers[0])
        self.assertLess(identifiers.index("b"), identifiers.index("a2"))
        self.assertLess(identifiers.index("c"), identifiers.index("a2"))
        self.assertLess(identifiers.index("d"), identifiers.index("a2"))

    def test_projection_does_not_drop_claims_for_a_local_token_budget(self):
        items = []
        for index in range(12):
            item = _Candidate({
                "id": f"distinct-{index}", "scope": "legacy:global",
                "claim_kind": "opaque_fact", "canonical_key": f"distinct:{index}",
                "slot_key": None, "display_text": f"Merkmal nummer{index} ist aktiv",
                "payload_json": "{}", "lifecycle": "active",
            }, score=4.0 - index / 100, requirement="useful", provenance=["user_stated"])
            items.append(item)

        rendered, selected, token_count, overflow, rejected = self.compiler._project(
            items, self.need(query="Welche Merkmale sind aktiv?"), {},
        )

        self.assertEqual(12, len(selected))
        self.assertLessEqual(token_count, 768)
        self.assertFalse(overflow)
        self.assertEqual({}, rejected)
        self.assertIn("Merkmal nummer11", rendered)


    def test_scope_candidate_retired_and_invalid_are_hard_boundaries(self):
        self.claim("scope", "Rollo Wohnzimmer fremd", scope="user:other")
        self.claim("candidate", "Rollo Wohnzimmer unsicher", lifecycle="candidate", slot="candidate")
        self.claim("retired", "Rollo Wohnzimmer alt", lifecycle="retired", slot="retired")
        self.claim("invalid", "Rollo Wohnzimmer falsch", lifecycle="invalid", slot="invalid")
        result = self.compiler.compile_turn("t", "answer", need=self.need())
        for forbidden in ("fremd", "unsicher", "alt", "falsch"):
            self.assertNotIn(forbidden, result["rendered_view"])
        audit = self.compiler.compile_turn(
            "t", "audit", need=self.need("audit", historical=True, audit=True)
        )
        self.assertIn("unsicher", audit["rendered_view"])
        self.assertIn("alt", audit["rendered_view"])
        self.assertIn("falsch", audit["rendered_view"])
        self.assertNotIn("fremd", audit["rendered_view"])

    def test_temporal_eligibility_normalizes_offsets_and_replays_retired_as_of_turn(self):
        claim = {
            "scope": "legacy:global", "lifecycle": "active",
            "valid_from": "2026-10-04T21:13:23+02:00", "valid_until": None,
        }
        need = self.need()
        self.assertIsNone(self.compiler._eligibility(claim, need, "2026-10-04T19:16:00+00:00"))
        self.assertEqual(
            "not_yet_valid",
            self.compiler._eligibility(claim, need, "2026-10-04T19:10:00+00:00"),
        )
        retired = {
            **claim, "lifecycle": "retired", "valid_from": "2026-10-04T19:00:00+00:00",
            "valid_until": "2026-10-04 19:19:25",
        }
        self.assertIsNone(self.compiler._eligibility(retired, need, "2026-10-04T19:17:50+00:00"))
        self.assertEqual(
            "retired_not_current",
            self.compiler._eligibility(retired, need, "2026-10-04T20:00:00+00:00"),
        )

    def test_conflict_is_never_ranked_away(self):
        self.claim("one", "Rollo Wohnzimmer ist cover.eins")
        self.claim("two", "Rollo Wohnzimmer ist cover.zwei")
        result = self.compiler.compile_turn("t", "answer", need=self.need())
        self.assertIn("cover.eins", result["rendered_view"])
        self.assertIn("cover.zwei", result["rendered_view"])
        self.assertEqual(2, result["rendered_view"].count("conflicted"))

    def test_binding_marks_stored_not_live_verified_without_tool_call(self):
        self.claim("binding", "Wohnzimmerrollo", kind="provider_binding", payload={
            "provider": "home_assistant", "subject": "Wohnzimmerrollo",
            "property": "position", "external_reference": "cover.rollade_wohnzimmer",
        })
        result = self.compiler.compile_turn(
            "t", "planner", need=self.need("planner", provider="home_assistant")
        )
        self.assertIn("stored_not_live_verified", result["rendered_view"])
        self.assertEqual(0, result["metrics"]["provider_calls"])
        self.assertEqual(0, result["metrics"]["llm_calls"])

    def test_exact_alias_is_required_without_semantic_special_case(self):
        self.claim("alias", "Elenas Sonnenschutz => Rollade Elena Rauf Runter",
                   kind="alias", slot=None, payload={
                       "alias": "Elenas Sonnenschutz",
                       "target": "Rollade Elena Rauf Runter",
                   })
        result = self.compiler.compile_turn(
            "t", "planner", need=MemoryNeed(
                "planner", "Öffne Elenas Sonnenschutz", ("legacy:global",),
                provider="home_assistant",
            ),
        )
        self.assertEqual("would_present", result["status"])
        self.assertIn("[required;", result["rendered_view"])
        self.assertIn("Rollade Elena Rauf Runter", result["rendered_view"])
        with self.database.connect() as c:
            reason = c.execute(
                "SELECT reason FROM memory_compiler_claim_audit WHERE claim_id='alias' "
                "AND stage='would_present'"
            ).fetchone()[0]
        self.assertIn("required_exact_alias", reason)

    def test_historical_tool_shapes_cover_all_original_error_classes(self):
        self.claim("binding", "Wohnzimmerrollo", kind="provider_binding", payload={
            "provider": "home_assistant", "subject": "Wohnzimmerrollo",
            "property": "resource", "external_reference": "cover.rollade_wohnzimmer",
        })
        cases = (
            ("binding", "Welche Entität ist das?", "rejected", "{}", "{}"),
            ("read", "Wie ist der Zustand?", "completed", '{"actions":["get_state"],"effect":"read"}', '{}'),
            ("write", "Fahre das Rollo hoch", "completed", '{"actions":["call_service"],"effect":"write"}', '{}'),
            ("camera", "Zeige die Kamera", "completed", '{"actions":["get_state"],"effect":"read"}',
             '{"resource":{"entity_id":"camera.front"}}'),
            ("history", "Zeige das Bild von gestern", "completed", '{"actions":["get_history"],"effect":"read"}', '[]'),
            ("followup", "Das habe ich dir gerade genannt", "unknown", "not-json", "null"),
        )
        with self.database.connect() as c:
            for index, (name, user, status, input_json, result_json) in enumerate(cases, 2):
                c.execute("INSERT INTO messages(id,conversation_id,role,content,ordinal,created_at) VALUES (?,?,?,?,?,'2026')",
                          (f"u-{name}", "c", "user", user, index * 2))
                c.execute("INSERT INTO messages(id,conversation_id,role,content,ordinal,created_at) VALUES (?,?,?,?,?,'2026')",
                          (f"a-{name}", "c", "assistant", "Antwort", index * 2 + 1))
                c.execute("""INSERT INTO turns(id,conversation_id,user_message_id,assistant_message_id,
                             knowledge_flow_json,created_at,completed_at) VALUES (?,?,?,?,?,'2026','2026')""",
                          (f"t-{name}", "c", f"u-{name}", f"a-{name}", "{}"))
                c.execute("""INSERT INTO conversation_tool_events
                             (id,conversation_id,message_id,ordinal,tool,status,summary,input_json,result_json,created_at)
                             VALUES (?,?,?,?,?,?,?,?,?,'2026')""",
                          (f"tool-{name}", "c", f"a-{name}", 0, "home_assistant", status, name,
                           input_json, result_json))
        for name, user, *_ in cases:
            for consumer in ("planner", "answer"):
                result = self.compiler.compile_turn(
                    f"t-{name}", consumer,
                    need=MemoryNeed(consumer, user, ("legacy:global",), provider="home_assistant"),
                )
                self.assertNotEqual("error", result["status"], (name, consumer))

    def test_legacy_budget_setting_does_not_hide_claims(self):
        for index in range(20):
            self.claim(str(index), "Rollo Wohnzimmer " + ("sehr lang " * 20) + str(index), slot=f"s:{index}")
        compiler = MemoryCompiler(self.database, config={"answer_budget": 64})
        result = compiler.compile_turn("t", "answer", need=self.need())
        self.assertEqual(20, result["presented_count"])
        self.assertFalse(result["required_overflow"])

    def test_rebuild_and_scale_candidate_pool_are_bounded(self):
        with self.database.connect() as c:
            for index in range(1000):
                c.execute("""INSERT INTO memory_claims
                    (id,claim_kind,scope,canonical_key,display_text,lifecycle,verification_policy,created_at,updated_at)
                    VALUES (?,'opaque_fact','legacy:global',?,?,'active','stable','2025','2025')""",
                    (f"bulk-{index}", f"bulk:{index}", f"Skalierung Eintrag {index}"))
        self.assertGreaterEqual(self.compiler.rebuild_fts(), 1000)
        result = self.compiler.compile_turn(
            "t", "answer", need=MemoryNeed("answer", "Skalierung Eintrag", ("legacy:global",))
        )
        self.assertEqual(1000, result["candidate_count"])

    def test_dense_thousand_claim_inventory_keeps_target_and_limits(self):
        with self.database.connect() as c:
            for index in range(1000):
                payload = json.dumps({
                    "provider": "home_assistant", "subject": f"Rollo Raum nummer{index}",
                    "property": "resource", "external_reference": f"cover.room_{index}",
                })
                c.execute("""INSERT INTO memory_claims
                    (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                     lifecycle,verification_policy,created_at,updated_at)
                    VALUES (?,'provider_binding','legacy:global',?,?,?,?,'active','configuration','2025','2025')""",
                    (f"dense-{index}", f"binding:{index}", f"room:{index}",
                     f"Rollo Raum nummer{index}", payload))
        result = self.compiler.compile_turn(
            "t", "planner", need=MemoryNeed(
                "planner", "Ressource für Rollo Raum nummer777", ("legacy:global",),
                provider="home_assistant", resources=("cover.room_777",),
            ),
        )
        self.assertIn("cover.room_777", result["rendered_view"])
        self.assertEqual(1, result["presented_count"])
        self.assertEqual(1000, result["candidate_count"])
        self.assertLessEqual(result["token_count"], result["token_budget"])

    def test_compiler_never_mutates_truth_tables(self):
        self.claim("x", "Rollo Wohnzimmer")
        with self.database.connect() as c:
            before = tuple(c.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                           for name in ("memory_claims", "memory_evidence", "memory_relations"))
        self.compiler.compile_turn("t", "answer", need=self.need())
        with self.database.connect() as c:
            after = tuple(c.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                          for name in ("memory_claims", "memory_evidence", "memory_relations"))
        self.assertEqual(before, after)

    def test_relevance_contract_rejects_eligible_claims_without_positive_need(self):
        for index, text in enumerate((
            "Der Sohn geht zur Schule", "Der Benutzername ist Stefan",
            "Das Rollo im Wohnzimmer ist offen", "Der Camp-Let hat eine Küche",
        )):
            self.claim(f"noise-{index}", text, slot=f"noise:{index}")
        for consumer in ("planner", "answer"):
            result = self.compiler.compile_turn(
                "t", consumer,
                need=MemoryNeed(consumer, "Servus EVE. Wie geht es dir?", ("legacy:global",)),
            )
            self.assertEqual("empty", result["status"])
            self.assertEqual(0, result["presented_count"])
            self.assertEqual("", result["rendered_view"])
        with self.database.connect() as c:
            reasons = {row[0] for row in c.execute(
                "SELECT reason FROM memory_compiler_claim_audit WHERE stage='rejected'"
            )}
        self.assertIn("no_positive_relevance", reasons)

    def test_bounded_semantic_set_keeps_coherent_broad_project_information(self):
        for identifier, text in (
            ("platform-events", "Die technische Plattform nutzt eine ereignisgesteuerte Nachrichtenvermittlung"),
            ("platform-storage", "Zur Plattform gehört eine revisionssichere Ablage"),
            ("platform-health", "Die Plattform wird durch automatisierte Zustandsprüfungen überwacht"),
        ):
            self.claim(identifier, text, slot=f"platform:{identifier}")

        result = self.compiler.preview(self.need(
            query=("Beschreibe umfassend die technische Plattform mit Aufbau, Komponenten, "
                   "Datenwegen, Betrieb, Wartung und Erweiterbarkeit."),
        ))

        selected = {claim["id"]: claim for claim in result["claims"]}
        self.assertEqual({"platform-events", "platform-storage", "platform-health"}, set(selected))
        self.assertTrue(all(
            "bounded_semantic_set" in claim["reasons"] for claim in selected.values()
        ))

    def test_bounded_semantic_set_rejects_unrelated_weak_surface_matches(self):
        for identifier, text in (
            ("platform-events", "Die technische Plattform nutzt eine ereignisgesteuerte Nachrichtenvermittlung"),
            ("platform-storage", "Zur Plattform gehört eine revisionssichere Ablage"),
            ("platform-health", "Die Plattform wird durch automatisierte Zustandsprüfungen überwacht"),
            ("travel", "Für die nächste Reise ist eine umfassende Routenplanung vorhanden"),
            ("politics", "Der Nutzer vertritt eine politische Meinung zum laufenden Betrieb"),
            ("household", "Im Haushalt stehen mehrere Komponenten im Küchenschrank"),
            ("purchase", "Die Kaufhistorie enthält technische Produkte"),
        ):
            self.claim(identifier, text, slot=f"broad:{identifier}")

        result = self.compiler.preview(self.need(
            query=("Beschreibe umfassend die technische Plattform mit Aufbau, Komponenten, "
                   "Datenwegen, Betrieb, Wartung und Erweiterbarkeit."),
        ))

        selected_ids = {claim["id"] for claim in result["claims"]}
        self.assertTrue({"platform-events", "platform-storage", "platform-health"} <= selected_ids)
        self.assertTrue({"travel", "politics", "household", "purchase"}.isdisjoint(selected_ids))

    def test_bounded_term_matching_accepts_word_forms_without_loose_four_char_prefixes(self):
        self.assertEqual(
            {"wartungsarbeiten"},
            self.compiler._bounded_term_matches(
                {"wartungsarbeiten"}, {"wartung", "plattform"},
            ),
        )
        self.assertEqual(
            set(),
            self.compiler._bounded_term_matches({"sichtbar"}, {"sich", "ansicht"}),
        )
        self.assertEqual(
            set(),
            self.compiler._bounded_term_matches({"verfügbaren"}, {"verfügt"}),
        )

    def test_dense_subject_inventory_keeps_only_exact_binding(self):
        for room in ("alpha", "beta", "gamma"):
            self.claim(f"blind-{room}", f"Rollo Zimmer {room}", kind="provider_binding",
                       slot=f"blind:{room}", payload={
                           "provider": "home_assistant", "subject": f"Rollo Zimmer {room}",
                           "property": "resource", "external_reference": f"cover.{room}",
                       })
        result = self.compiler.compile_turn(
            "t", "planner", need=MemoryNeed(
                "planner", "Welche Ressource hat das Rollo im Zimmer beta?",
                ("legacy:global",), provider="home_assistant",
            ),
        )
        self.assertIn("cover.beta", result["rendered_view"])
        self.assertNotIn("cover.alpha", result["rendered_view"])
        self.assertNotIn("cover.gamma", result["rendered_view"])

    def test_relevant_preference_is_answer_only(self):
        self.claim("preference", "Kaufpräferenz: gebrauchte Standard-Hardware", slot="preference:hardware")
        need = "Welche gebrauchte Hardware bevorzuge ich?"
        answer = self.compiler.compile_turn(
            "t", "answer", need=MemoryNeed("answer", need, ("legacy:global",), general_memory_needed=True)
        )
        planner = self.compiler.compile_turn(
            "t", "planner", need=MemoryNeed("planner", need, ("legacy:global",), general_memory_needed=True)
        )
        self.assertIn("Kaufpräferenz", answer["rendered_view"])
        self.assertEqual(0, planner["presented_count"])

    def test_conversation_reference_can_recover_binding_for_short_followup(self):
        self.claim("binding", "Wohnzimmerrollo", kind="provider_binding", payload={
            "provider": "home_assistant", "subject": "Rollo Wohnzimmer",
            "property": "resource", "external_reference": "cover.wohnzimmer",
        })
        result = self.compiler.compile_turn(
            "t", "planner", need=MemoryNeed(
                "planner", "Und davon?", ("legacy:global",), provider="home_assistant",
                conversation_text="Welche Ressource hat das Rollo im Wohnzimmer?",
            ),
        )
        self.assertIn("cover.wohnzimmer", result["rendered_view"])

    def test_high_lexical_score_with_wrong_subject_is_rejected(self):
        self.claim("binding", "Rollo Zimmer beta", kind="provider_binding", payload={
            "provider": "home_assistant", "subject": "Rollo Zimmer beta",
            "property": "resource", "external_reference": "cover.beta",
        })
        self.claim("wrong", "Rollo Zimmer alpha fährt herunter", slot="rule:alpha")
        result = self.compiler.compile_turn(
            "t", "answer", need=MemoryNeed(
                "answer", "Rollo Zimmer beta herunterfahren", ("legacy:global",),
                provider="home_assistant",
            ),
        )
        self.assertIn("cover.beta", result["rendered_view"])
        self.assertNotIn("alpha", result["rendered_view"])

    def test_media_reference_uses_structured_resource_without_device_expansion(self):
        self.claim("camera", "Haustürkamera", kind="provider_binding", slot="camera:front", payload={
            "provider": "home_assistant", "subject": "Haustürkamera",
            "property": "resource", "external_reference": "camera.front_door",
        })
        self.claim("other", "Wohnzimmerrollo", kind="provider_binding", slot="blind:living", payload={
            "provider": "home_assistant", "subject": "Wohnzimmerrollo",
            "property": "resource", "external_reference": "cover.living",
        })
        result = self.compiler.compile_turn(
            "t", "planner", need=MemoryNeed(
                "planner", "Zeige das Bild", ("legacy:global",), provider="home_assistant",
                resources=("camera.front_door",), historical=True,
            ),
        )
        self.assertIn("camera.front_door", result["rendered_view"])
        self.assertNotIn("cover.living", result["rendered_view"])

    def test_retrieval_ablation_preserves_structured_and_exposes_fts_value(self):
        self.claim("binding", "Rollo Zimmer beta", kind="provider_binding", payload={
            "provider": "home_assistant", "subject": "Rollo Zimmer beta",
            "property": "resource", "external_reference": "cover.beta",
        })
        self.claim("preference", "Kaufpräferenz gebrauchte Standard-Hardware", slot="pref:hardware")
        structured = MemoryCompiler(self.database, config={"retrieval_mode": "structured_only"})
        exact = structured.compile_turn(
            "t", "planner", need=MemoryNeed(
                "planner", "Rollo beta", ("legacy:global",), provider="home_assistant",
                resources=("cover.beta",),
            ),
        )
        opaque_without_fts = structured.compile_turn(
            "t", "answer", need=MemoryNeed(
                "answer", "Welche gebrauchte Hardware bevorzuge ich?", ("legacy:global",),
                general_memory_needed=True,
            ),
        )
        opaque_with_fts = self.compiler.compile_turn(
            "t", "answer", need=MemoryNeed(
                "answer", "Welche gebrauchte Hardware bevorzuge ich?", ("legacy:global",),
                general_memory_needed=True,
            ),
        )
        self.assertIn("cover.beta", exact["rendered_view"])
        self.assertEqual(0, opaque_without_fts["presented_count"])
        self.assertIn("Kaufpräferenz", opaque_with_fts["rendered_view"])

    def test_interactive_priority_cancels_shadow_without_truth_mutation(self):
        self.claim("x", "Rollo Wohnzimmer")
        started = threading.Event()
        release = threading.Event()
        original = self.compiler._retrieve

        def delayed(need):
            started.set()
            release.wait(2)
            return original(need)

        self.compiler._retrieve = delayed
        before = self.compiler.priority_token()
        holder = {}
        thread = threading.Thread(target=lambda: holder.setdefault(
            "result", self.compiler.compile_turn("t", "answer", need=self.need(),
                                                 expected_priority_generation=before)
        ))
        thread.start()
        self.assertTrue(started.wait(1))
        priority_started = time.perf_counter()
        self.compiler.prioritize_interactive_turn()
        self.assertLess(time.perf_counter() - priority_started, 0.1)
        release.set()
        thread.join(2)
        self.assertEqual("cancelled", holder["result"]["status"])
        with self.database.connect() as c:
            self.assertEqual(1, c.execute("SELECT count(*) FROM memory_claims").fetchone()[0])
            self.assertEqual(0, c.execute("SELECT count(*) FROM memory_evidence").fetchone()[0])

    def test_controlled_required_recall_is_complete(self):
        bindings = {
            "cover.rollade_wohnzimmer": "Rollo Wohnzimmer",
            "light.kueche": "Licht Küche",
            "sensor.tesla_battery": "Batterie Tesla",
        }
        for index, (reference, wording) in enumerate(bindings.items()):
            self.claim(f"binding-{index}", wording, kind="provider_binding", slot=f"slot:{index}", payload={
                "provider": "home_assistant", "subject": wording, "property": "resource",
                "external_reference": reference,
            })
        for reference in bindings:
            result = self.compiler.compile_turn(
                "t", "planner", need=self.need(
                    "planner", provider="home_assistant", resources=(reference,), query=reference,
                ),
            )
            self.assertIn(reference, result["rendered_view"])
        self.assertEqual(3, len(bindings))

    def test_fts_failure_has_bounded_sql_fallback(self):
        self.claim("x", "Rollo Wohnzimmer Fallback")
        with self.database.connect() as c:
            c.execute("DROP TABLE memory_claims_fts")
        result = self.compiler.compile_turn("t", "answer", need=self.need())
        self.assertIn("Fallback", result["rendered_view"])


class MemoryCompilerMigrationTest(unittest.TestCase):
    def test_v10_upgrade_is_backed_up_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.db"
            database = EveDatabase(path)
            with database.connect() as c:
                c.execute("DROP TABLE memory_compiler_claim_audit")
                c.execute("DROP TABLE memory_compiler_evaluations")
                c.execute("DROP TABLE memory_claims_fts")
                c.execute("PRAGMA user_version=10")
            database = EveDatabase(path)
            EveDatabase(path)
            backups = list((path.parent / "backups").glob(f"eve-schema-v10-to-v{SCHEMA_VERSION}-*.db"))
            self.assertEqual(1, len(backups))
            with database.connect() as c:
                self.assertEqual(SCHEMA_VERSION, c.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual("ok", c.execute("PRAGMA integrity_check").fetchone()[0])
                self.assertEqual(0, len(c.execute("PRAGMA foreign_key_check").fetchall()))
            with sqlite3.connect(backups[0]) as backup:
                self.assertEqual(10, backup.execute("PRAGMA user_version").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
