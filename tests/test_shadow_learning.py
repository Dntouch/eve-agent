import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eve_agent.shadow_learning import ProductiveLearningPipeline, ShadowLearningPipeline
from eve_agent.storage import ConversationStore, EveDatabase, SCHEMA_VERSION


class FakeLearningLLM:
    model = "fake-learning-model"

    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = 0
        self.contexts = []

    def analyze_shadow_learning(self, context):
        self.calls += 1
        self.contexts.append(context)
        return json.loads(json.dumps(self.proposal))


def proposal(
    decision="create_active", *, kind="opaque_fact", scope="user:self",
    canonical="v2:preference:user:self:breakfast", slot="v2:preference:user:self:breakfast",
    lifecycle="active", authority="user_direct", evidence=None, matched=None, relations=None,
):
    return {
        "decision_type": decision, "memory_worthy": decision != "no_persist",
        "reason_code": "stable_user_information", "uncertainty": .1,
        "clarification_recommended": False, "authority": authority,
        "temporal_class": "stable",
        "claim": None if decision == "no_persist" else {
            "kind": kind, "scope": scope, "canonical_key": canonical, "slot_key": slot,
            "lifecycle": lifecycle, "display_text": "Der Benutzer bevorzugt morgens Haferbrei.",
            "payload": {"subject": "user:self", "property": "breakfast", "value": "Haferbrei"},
            "valid_from": None, "valid_until": None,
        },
        "evidence": evidence or [], "matched_claim_ids": matched or [], "relations": relations or [],
    }


class ShadowLearningTest(unittest.TestCase):
    def test_integration_events_are_not_learned_or_used_as_later_dialog_context(self):
        source={'mcp_wakeup':{'server':'fixture','method':'notifications/eve/test',
                              'event_id':'fixture:event-0001'}}
        self.conversations.append_turn(
            self.conversation_id, 'Fixture event', 'Synthetic event answer',
            turn_id='event-turn', user_metadata={'conversation_source':source})
        fake=FakeLearningLLM(proposal())
        for pipeline_type in (ShadowLearningPipeline,ProductiveLearningPipeline):
            pipeline=pipeline_type(self.database,fake)
            result=pipeline.evaluate_turn('event-turn')
            self.assertEqual(result['decision_type'],'no_persist')
            self.assertEqual(result['reason_code'],'integration_event')
        self.assertEqual(fake.calls,0)
        later,_=self.turn('Normal follow-up')
        history=ShadowLearningPipeline(self.database)._snapshot(later)['dialog_context']
        self.assertEqual(history,[])

    def test_scheduled_input_keeps_automatic_origin_in_learning_and_evidence(self):
        metadata = {'input_kind': 'scheduled', 'scheduled_execution': {
            'task_id': 'task', 'run_id': 'run', 'origin_source': {'sender_name': 'Stefan'}}}
        user, _ = self.conversations.append_turn(self.conversation_id, 'Erinnere ZappyZwo jetzt',
            'ZappyZwo, heute hast du frei.', turn_id='scheduled-turn', user_metadata=metadata)
        for pipeline_type in (ShadowLearningPipeline, ProductiveLearningPipeline):
            fake = FakeLearningLLM(proposal(decision='no_persist'))
            pipeline = pipeline_type(self.database, fake)
            snapshot = pipeline._snapshot('scheduled-turn')
            context = pipeline._model_context(snapshot, [])
            self.assertEqual(context['user_message']['scheduled_execution']['run_id'], 'run')
            self.assertFalse(context['user_message']['fresh_human_message'])
            pipeline.evaluate_turn('scheduled-turn')
        with self.database.connect() as c:
            observation = c.execute('SELECT source_role,metadata_json FROM memory_observations WHERE message_id=?', (user['id'],)).fetchone()
        self.assertEqual(observation['source_role'], 'system')
        self.assertEqual(json.loads(observation['metadata_json'])['scheduled_execution']['task_id'], 'task')
        next_turn, _ = self.turn('Was war das?')
        history = ShadowLearningPipeline(self.database)._snapshot(next_turn)['dialog_context']
        self.assertEqual(history[0]['scheduled_execution']['run_id'], 'run')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = EveDatabase(Path(self.temp.name) / "eve.db")
        self.conversations = ConversationStore(self.database)
        self.conversation_id = self.conversations.create("Shadow")['id']

    def tearDown(self):
        self.temp.cleanup()

    def turn(self, user, *, route="chat", tools=None, retrievals=None):
        turn_id = "turn-" + str(abs(hash((user, route, len(tools or [])))))
        user_row, _assistant = self.conversations.append_turn(
            self.conversation_id, user, "Kontextantwort", turn_id=turn_id,
            assistant_metadata={"route": route}, tool_events=tools or [],
            memory_retrievals=retrievals or [],
        )
        return turn_id, user_row["id"]

    def counts(self):
        with self.database.connect() as connection:
            return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in (
                "memory_claims", "memory_evidence", "memory_relations", "memory_items",
            ))

    def test_dialog_context_is_prior_same_conversation_and_not_evidence(self):
        self.turn("Private Informationen bleiben privat.")
        other = self.conversations.create("Other")['id']
        self.conversations.append_turn(other, "Unrelated private message", "Other answer", turn_id="other-turn")
        turn_id, _ = self.turn("Das gilt auch gegenüber mir.")
        self.turn("Future information")
        pipeline = ShadowLearningPipeline(self.database)
        snapshot = pipeline._snapshot(turn_id)
        history = snapshot['dialog_context']
        self.assertEqual([item['role'] for item in history], ['user', 'assistant'])
        self.assertEqual(history[0]['content'], "Private Informationen bleiben privat.")
        self.assertTrue(all(item['context_only'] for item in history))
        self.assertTrue(all('evidence_reference' not in item for item in history))
        context = pipeline._model_context(snapshot, [])
        self.assertEqual(context['dialog_context'], history)
        self.assertIn(history[0]['content'], pipeline._candidate_context(snapshot))

    def test_stable_preference_creates_only_shadow_proposal(self):
        turn_id, message_id = self.turn("Zum Frühstück bevorzuge ich meist Haferbrei.")
        fake = FakeLearningLLM(proposal(evidence=[{
            "source_type": "user_message", "source_id": message_id, "stance": "supports",
            "property": None, "external_reference": None,
        }]))
        before = self.counts()
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("create_active", result["decision_type"])
        self.assertEqual(before, self.counts())
        with self.database.connect() as connection:
            self.assertEqual(1, connection.execute("SELECT count(*) FROM memory_shadow_learning_decisions").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT count(*) FROM memory_observations").fetchone()[0])

    def test_structured_write_turn_is_judged_by_the_model(self):
        turn_id, _ = self.turn(
            "Stelle die Lampe auf eine andere Helligkeit.", route="home",
            tools=[{"tool": "home_assistant", "status": "completed", "summary": "ausgeführt",
                    "input": {"actions": ["call_service"]}, "result": {"status": "success"}}],
        )
        fake = FakeLearningLLM(proposal(decision="no_persist"))
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("no_persist", result["decision_type"])
        self.assertEqual(1, fake.calls)

    def test_unique_successful_named_provider_resolution_becomes_active_binding(self):
        tools = [{
            "tool": "home_assistant", "status": "completed", "summary": "gelesen",
            "input": {"actions": ["get_state"]},
            "result": {
                "status": "success",
                "resolved_resources": [{
                    "entity_id": "cover.parent_bedroom", "name": "Rollo Elternschlafzimmer",
                    "namespace": "cover",
                }],
            },
        }]
        turn_id, _ = self.turn(
            "Ist das Rollo im Elternschlafzimmer geschlossen?", route="home", tools=tools,
        )
        with self.database.connect() as connection:
            tool_id = connection.execute(
                "SELECT id FROM conversation_tool_events WHERE message_id IN "
                "(SELECT assistant_message_id FROM turns WHERE id=?)", (turn_id,),
            ).fetchone()[0]
        learned = proposal(
            kind="provider_binding", scope="household:default",
            canonical="v2:model-selected", slot="v2:model-selected",
            evidence=[
                {"source_type": "user_message", "source_id": _, "stance": "supports",
                 "property": None, "external_reference": None},
                {"source_type": "provider_result", "source_id": tool_id, "stance": "supports",
                 "property": "entity_id", "external_reference": "cover.parent_bedroom"},
            ],
        )
        learned["claim"]["payload"] = {
            "provider": "home_assistant", "subject": "Rollo Elternschlafzimmer",
            "property": "resource", "external_reference": "cover.parent_bedroom",
        }
        fake = FakeLearningLLM(learned)

        result = ProductiveLearningPipeline(self.database, fake).process_turn(turn_id)

        self.assertEqual("create_active", result["decision_type"])
        self.assertEqual("stable_user_information", result["reason_code"])
        self.assertEqual(1, fake.calls)
        with self.database.connect() as connection:
            claim = connection.execute(
                "SELECT * FROM memory_claims WHERE claim_kind='provider_binding'"
            ).fetchone()
        self.assertEqual("active", claim["lifecycle"])
        self.assertIn("cover.parent_bedroom", claim["payload_json"])

    def test_implicit_provider_followup_does_not_create_a_binding(self):
        tools = [{
            "tool": "home_assistant", "status": "completed", "summary": "gelesen",
            "input": {"actions": ["get_state"]},
            "result": {
                "status": "success",
                "resolved_resources": [{
                    "entity_id": "cover.parent_bedroom", "name": "Rollo Elternschlafzimmer",
                }],
            },
        }]
        turn_id, _ = self.turn("Und ist es jetzt zu?", route="home", tools=tools)
        fake = FakeLearningLLM(proposal(decision="no_persist"))

        result = ProductiveLearningPipeline(self.database, fake).process_turn(turn_id)

        self.assertEqual("no_persist", result["decision_type"])
        self.assertEqual(1, fake.calls)
        with self.database.connect() as connection:
            count = connection.execute(
                "SELECT count(*) FROM memory_claims WHERE claim_kind='provider_binding'"
            ).fetchone()[0]
        self.assertEqual(0, count)

    def test_model_inference_can_never_activate_claim(self):
        turn_id, _ = self.turn("Aus dem Kontext könnte sich eine Vorliebe ergeben.")
        fake = FakeLearningLLM(proposal(authority="model_inference"))
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("create_candidate", result["decision_type"])
        self.assertEqual("candidate", result["claim"]["lifecycle"])

    def test_uncertain_user_statement_remains_candidate(self):
        turn_id, _ = self.turn("Die Zuordnung könnte stimmen, ich bin mir aber nicht sicher.")
        fake = FakeLearningLLM(proposal(decision="create_candidate", lifecycle="candidate"))
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("create_candidate", result["decision_type"])
        self.assertNotEqual("active", result["claim"]["lifecycle"])

    def test_assistant_retrieval_and_usage_cannot_be_evidence(self):
        for source_type in ("assistant_output", "retrieved_memory", "memory_used"):
            turn_id, _ = self.turn("Prüfe diese Aussage " + source_type)
            fake = FakeLearningLLM(proposal(evidence=[{
                "source_type": source_type, "source_id": "invented", "stance": "supports",
            }]))
            result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
            self.assertEqual("undetermined", result["decision_type"])
            self.assertEqual("non_evidence_source", result["reason_code"])

    def test_same_canonical_key_appends_evidence_in_proposal_only(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('known','opaque_fact','user:self','v2:preference:user:self:breakfast',
                           'v2:preference:user:self:breakfast','Haferbrei am Morgen','active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Morgens esse ich weiterhin gern Haferbrei.")
        fake = FakeLearningLLM(proposal(evidence=[{
            "source_type": "user_message", "source_id": message_id, "stance": "supports",
            "property": None, "external_reference": None,
        }]))
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("append_supporting_evidence", result["decision_type"])
        self.assertEqual(["known"], result["matched_claim_ids"])
        self.assertEqual((1, 0, 0, 0), self.counts())

    def test_same_slot_different_value_is_competing_not_blind_supersession(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('old','opaque_fact','user:self','v2:preference:user:self:tea',
                           'v2:preference:user:self:drink','Der Benutzer bevorzugt Tee','active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Mein übliches Getränk ist inzwischen Wasser.")
        fake = FakeLearningLLM(proposal(
            canonical="v2:preference:user:self:water", slot="v2:preference:user:self:drink",
            evidence=[{"source_type": "user_message", "source_id": message_id,
                       "stance": "supports", "property": None, "external_reference": None}],
        ))
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("create_competing_claim", result["decision_type"])
        self.assertEqual("candidate", result["claim"]["lifecycle"])
        self.assertEqual(["old"], result["matched_claim_ids"])

    def test_explicit_correction_is_only_a_planned_supersession(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('old-color','opaque_fact','user:self','v2:preference:user:self:blue',
                           'v2:preference:user:self:color','Meine bevorzugte Farbe war blau',
                           'active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Korrektur zu meiner bevorzugten Farbe: Sie ist grün statt blau.")
        correction = proposal(
            decision="supersede_claim", canonical="v2:preference:user:self:green",
            slot="v2:preference:user:self:color", matched=["old-color"],
            relations=[{"relation_type": "supersedes", "target_claim_id": "old-color"}],
            evidence=[{"source_type": "user_message", "source_id": message_id,
                       "stance": "supports", "property": None, "external_reference": None}],
        )
        correction["change_type"] = "correction"
        fake = FakeLearningLLM(correction)
        before = self.counts()
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("supersede_claim", result["decision_type"])
        self.assertEqual(before, self.counts())
        with self.database.connect() as connection:
            self.assertEqual("active", connection.execute(
                "SELECT lifecycle FROM memory_claims WHERE id='old-color'"
            ).fetchone()[0])

    def test_explicit_bounded_time_is_preserved_but_invalid_time_is_rejected(self):
        turn_id, message_id = self.turn("Diese Projektregel gilt während des kommenden Quartals.")
        bounded = proposal(evidence=[{"source_type": "user_message", "source_id": message_id,
                                      "stance": "supports", "property": None, "external_reference": None}])
        bounded["claim"]["valid_from"] = "2027-01-01"
        bounded["claim"]["valid_until"] = "2027-03-31"
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(bounded)).evaluate_turn(turn_id)
        self.assertEqual("2027-03-31", result["claim"]["valid_until"])

        bad_turn, bad_message = self.turn("Der Zeitraum ist nicht belastbar angegeben.")
        invalid = proposal(evidence=[{"source_type": "user_message", "source_id": bad_message,
                                      "stance": "supports", "property": None, "external_reference": None}])
        invalid["claim"]["valid_until"] = "irgendwann"
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(invalid)).evaluate_turn(bad_turn)
        self.assertEqual("undetermined", result["decision_type"])
        self.assertEqual("invalid_time_value", result["reason_code"])

    def test_similarity_cannot_override_identity_or_scope(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,lifecycle,verification_policy,created_at,updated_at)
                   VALUES ('other','opaque_fact','user:other','v2:device:other:shade',
                           'Das Rollo im Arbeitszimmer gehört einer anderen Person','active','unknown','2026','2026')"""
            )
        turn_id, _ = self.turn("Das Rollo im Arbeitszimmer gehört zu meinem Bereich.")
        fake = FakeLearningLLM(proposal(
            decision="append_supporting_evidence", scope="user:self",
            canonical="v2:device:user:self:shade", matched=["other"],
        ))
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("undetermined", result["decision_type"])
        self.assertIn(result["reason_code"], {
            "scope_mismatch", "semantic_similarity_is_not_identity", "append_requires_evidence",
        })

    def test_provider_evidence_is_property_specific_and_referenced(self):
        tools = [{
            "tool": "home_assistant", "status": "completed", "summary": "gelesen",
            "input": {"actions": ["get_state"]},
            "result": {"resolved_resources": [{"entity_id": "sensor.office_humidity"}]},
        }]
        turn_id, message_id = self.turn(
            "Der Bürosensor ist meine Referenz für Luftfeuchte.", route="home", tools=tools,
        )
        with self.database.connect() as connection:
            tool_id = connection.execute("SELECT id FROM conversation_tool_events").fetchone()[0]
        binding = proposal(
            kind="provider_binding", canonical="provider_binding:user:self:office:humidity",
            slot="provider_binding:user:self:office:humidity",
            evidence=[
                {"source_type": "user_message", "source_id": message_id, "stance": "supports",
                 "property": None, "external_reference": None},
                {"source_type": "provider_result", "source_id": tool_id, "stance": "supports",
                 "property": "existence", "external_reference": "sensor.office_humidity"},
            ],
        )
        binding["claim"]["payload"] = {
            "provider": "home_assistant", "subject": "office",
            "property": "humidity", "external_reference": "sensor.office_humidity",
        }
        fake = FakeLearningLLM(binding)
        result = ShadowLearningPipeline(self.database, fake).evaluate_turn(turn_id)
        self.assertEqual("create_active", result["decision_type"])
        with self.database.connect() as connection:
            provider = connection.execute(
                "SELECT * FROM memory_observations WHERE source_type='provider_result'"
            ).fetchone()
        self.assertEqual(tool_id, provider["tool_event_id"])
        self.assertNotIn("resolved_resources", provider["structured_value_json"])

    def test_append_contract_needs_target_and_evidence_but_no_claim(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('komet','opaque_fact','device:test-device','v2:device:name:komet',
                           'v2:device:name','Das Testgerät heißt Komet','active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Zur Bestätigung: Das Testgerät nenne ich Komet.")
        raw = proposal(decision="append_supporting_evidence", matched=["komet"], evidence=[{
            "source_type": "user_message", "source_id": message_id, "stance": "supports",
            "property": None, "external_reference": None,
        }])
        raw["claim"] = None
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("append_supporting_evidence", result["decision_type"])
        self.assertIsNone(result["claim"])
        self.assertEqual("komet", result["evidence"][0]["target_claim_id"])
        self.assertEqual([], result["relations"])

    def test_exact_structural_identity_normalizes_reconfirmation_to_append(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('known-name','opaque_fact','device:test-device','v2:device:name:komet',
                           'v2:device:name','Das Testgerät heißt Komet','active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Komet bleibt der Name des Testgeräts.")
        raw = proposal(
            scope="device:test-device", canonical="v2:device:name:komet", slot="v2:device:name",
            evidence=[{"source_type": "user_message", "source_id": message_id,
                       "stance": "supports", "property": None, "external_reference": None}],
        )
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("append_supporting_evidence", result["decision_type"])
        self.assertIsNone(result["claim"])
        self.assertEqual(["known-name"], result["matched_claim_ids"])

    def test_incidental_reuse_need_not_create_evidence(self):
        turn_id, _ = self.turn("Bei Komet, also meinem Testgerät, wollte ich noch etwas prüfen.")
        result = ShadowLearningPipeline(
            self.database, FakeLearningLLM(proposal(decision="no_persist")),
        ).evaluate_turn(turn_id)
        self.assertEqual("no_persist", result["decision_type"])
        self.assertEqual([], result["evidence"])

    def test_competing_contract_normalizes_missing_lifecycle_to_candidate(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('komet','opaque_fact','device:test-device','v2:device:name:komet',
                           'v2:device:name','Das Testgerät heißt Komet','active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Nova wäre ebenfalls ein möglicher Name.")
        raw = proposal(
            decision="create_competing_claim", scope="device:test-device",
            canonical="v2:device:name:nova", slot="v2:device:name", matched=["komet"],
            evidence=[{"source_type": "user_message", "source_id": message_id,
                       "stance": "supports", "property": None, "external_reference": None}],
        )
        raw["claim"].pop("lifecycle")
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("create_competing_claim", result["decision_type"])
        self.assertEqual("candidate", result["claim"]["lifecycle"])
        self.assertEqual([], result["relations"])
        self.assertEqual("new_claim", result["evidence"][0]["target_claim_id"])

    def test_competing_contract_does_not_invent_missing_scope(self):
        turn_id, message_id = self.turn("Nova wäre ebenfalls ein möglicher Name.")
        raw = proposal(decision="create_competing_claim", evidence=[{
            "source_type": "user_message", "source_id": message_id, "stance": "supports",
            "property": None, "external_reference": None,
        }])
        raw["claim"].pop("scope")
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("undetermined", result["decision_type"])
        self.assertEqual("invalid_claim_identity", result["reason_code"])

    def test_supersession_contract_projects_atomic_evidence_and_retirement(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('komet','opaque_fact','device:test-device','v2:device:name:komet',
                           'v2:device:name','Das Testgerät heißt Komet','active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Nein, das Testgerät heißt nicht Komet, sondern Nova.")
        raw = proposal(
            decision="supersede_claim", scope="device:test-device", canonical="v2:device:name:nova",
            slot="v2:device:name", matched=["komet"], evidence=[{
                "source_type": "user_message", "source_id": message_id, "stance": "supports",
                "property": None, "external_reference": None,
            }],
        )
        raw["change_type"] = "correction"
        raw["relations"] = []
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("supersede_claim", result["decision_type"])
        self.assertEqual({"supports", "contradicts"}, {item["stance"] for item in result["evidence"]})
        self.assertEqual({"new_claim", "komet"}, {item["target_claim_id"] for item in result["evidence"]})
        self.assertEqual([{"relation_type": "supersedes", "target_claim_id": "komet"}], result["relations"])
        self.assertEqual("retired", result["details"]["old_claim_transition"]["proposed_lifecycle"])

    def test_temporal_supersession_ends_validity_without_calling_old_claim_false(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('old','opaque_fact','project:orion','v2:project:orion:alpha',
                           'v2:project:orion:variant','Orion nutzt Alpha','active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Ab 2027-01-01 gilt für Orion Beta statt Alpha.")
        raw = proposal(
            decision="supersede_claim", scope="project:orion", canonical="v2:project:orion:beta",
            slot="v2:project:orion:variant", matched=["old"], evidence=[{
                "source_type": "user_message", "source_id": message_id, "stance": "supports",
                "property": None, "external_reference": None,
            }],
        )
        raw["change_type"] = "temporal_change"
        raw["claim"]["valid_from"] = "2027-01-01"
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("supersede_claim", result["decision_type"])
        self.assertEqual({"supports"}, {item["stance"] for item in result["evidence"]})
        self.assertEqual("2027-01-01", result["details"]["old_claim_transition"]["valid_until"])

    def test_provider_binding_contract_normalizes_keys_but_not_semantics(self):
        tools = [{
            "tool": "home_assistant", "status": "completed", "summary": "gelesen",
            "input": {"actions": ["get_state"]},
            "result": {"resolved_resources": [{"entity_id": "sensor.office_humidity", "state": "48"}]},
        }]
        turn_id, message_id = self.turn("Der Bürosensor steht dauerhaft für Luftfeuchte.", route="home", tools=tools)
        with self.database.connect() as connection:
            tool_id = connection.execute("SELECT id FROM conversation_tool_events").fetchone()[0]
        raw = proposal(
            kind="provider_binding", scope="device:office-sensor", canonical="v2:ignored",
            slot=None, evidence=[
                {"source_type": "user_message", "source_id": message_id, "stance": "supports",
                 "property": None, "external_reference": None},
                {"source_type": "provider_result", "source_id": tool_id, "stance": "supports",
                 "property": "entity_id", "external_reference": "sensor.office_humidity"},
            ],
        )
        raw["claim"]["payload"] = {
            "provider": "home_assistant", "subject": "office", "property": "humidity",
            "external_reference": "sensor.office_humidity",
        }
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("create_active", result["decision_type"])
        self.assertEqual(
            "provider_binding:home_assistant:office:humidity:sensor.office_humidity",
            result["claim"]["canonical_key"],
        )
        self.assertEqual("provider_binding:home_assistant:office:humidity", result["claim"]["slot_key"])
        self.assertEqual("configuration", result["claim"]["verification_policy"])

    def test_scope_normalizes_only_safe_syntax(self):
        turn_id, message_id = self.turn("Eine stabile Projektinformation.")
        raw = proposal(scope="Project:Orion_Test", evidence=[{
            "source_type": "user_message", "source_id": message_id, "stance": "supports",
            "property": None, "external_reference": None,
        }])
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("project:orion-test", result["claim"]["scope"])

        bad_turn, bad_message = self.turn("Eine Information mit unklarem Scope.")
        invalid = proposal(scope="frei erfundener scope", evidence=[{
            "source_type": "user_message", "source_id": bad_message, "stance": "supports",
            "property": None, "external_reference": None,
        }])
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(invalid)).evaluate_turn(bad_turn)
        self.assertEqual("invalid_scope", result["reason_code"])

    def test_provider_binding_rejects_unobserved_reference_and_missing_user_source(self):
        tools = [{
            "tool": "home_assistant", "status": "completed", "summary": "gelesen",
            "input": {"actions": ["get_state"]},
            "result": {"resolved_resources": [{"entity_id": "sensor.office_humidity"}]},
        }]
        turn_id, _ = self.turn("Prüfe den Sensor.", route="home", tools=tools)
        with self.database.connect() as connection:
            tool_id = connection.execute("SELECT id FROM conversation_tool_events").fetchone()[0]
        raw = proposal(kind="provider_binding", scope="device:office-sensor", canonical="v2:ignored", evidence=[{
            "source_type": "provider_result", "source_id": tool_id, "stance": "supports",
            "property": "entity_id", "external_reference": "sensor.invented",
        }])
        raw["claim"]["payload"] = {
            "provider": "home_assistant", "subject": "office", "property": "humidity",
            "external_reference": "sensor.invented",
        }
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("provider_evidence_not_observed", result["reason_code"])

    def test_provider_binding_rejects_subject_copied_from_unrelated_candidate(self):
        tools = [{
            "tool": "home_assistant", "status": "completed", "summary": "gelesen",
            "input": {"actions": ["get_state"]},
            "result": {"resolved_resources": [{"entity_id": "sensor.office_humidity"}]},
        }]
        turn_id, message_id = self.turn(
            "Der Sensor im Arbeitszimmer steht für Luftfeuchte.", route="home", tools=tools,
        )
        with self.database.connect() as connection:
            tool_id = connection.execute("SELECT id FROM conversation_tool_events").fetchone()[0]
        raw = proposal(
            kind="provider_binding", scope="device:unrelated-alpha", canonical="v2:ignored", evidence=[
                {"source_type": "user_message", "source_id": message_id, "stance": "supports",
                 "property": None, "external_reference": None},
                {"source_type": "provider_result", "source_id": tool_id, "stance": "supports",
                 "property": "entity_id", "external_reference": "sensor.office_humidity"},
            ],
        )
        raw["claim"]["payload"] = {
            "provider": "home_assistant", "subject": "device:unrelated-alpha",
            "property": "humidity", "external_reference": "sensor.office_humidity",
        }
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual("undetermined", result["decision_type"])
        self.assertEqual("provider_binding_subject_not_grounded", result["reason_code"])

    def test_refine_contract_keeps_old_claim_and_creates_refines_relation(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('broad','opaque_fact','project:orion','v2:project:orion:rule',
                           'Orion nutzt kurze Meldungen','active','stable','2026','2026')"""
            )
        turn_id, message_id = self.turn("Für Orion sollen Fehlermeldungen höchstens zwei Sätze lang sein.")
        raw = proposal(
            decision="refine_claim", scope="project:orion", canonical="v2:project:orion:error-length",
            slot=None, matched=["broad"], evidence=[{
                "source_type": "user_message", "source_id": message_id, "stance": "supports",
                "property": None, "external_reference": None,
            }],
        )
        result = ShadowLearningPipeline(self.database, FakeLearningLLM(raw)).evaluate_turn(turn_id)
        self.assertEqual([{"relation_type": "refines", "target_claim_id": "broad"}], result["relations"])
        self.assertEqual("active", result["details"]["old_claim_transition"]["proposed_lifecycle"])

    def test_idempotency_and_policy_re_evaluation(self):
        turn_id, _ = self.turn("Eine langfristig zu prüfende Information.")
        first = ShadowLearningPipeline(self.database, FakeLearningLLM(proposal()))
        first.evaluate_turn(turn_id)
        first.evaluate_turn(turn_id)
        second = ShadowLearningPipeline(
            self.database, FakeLearningLLM(proposal(decision="create_candidate", lifecycle="candidate")),
            policy_version="memory-v2-shadow-v2",
        )
        second.evaluate_turn(turn_id)
        with self.database.connect() as connection:
            self.assertEqual(2, connection.execute("SELECT count(*) FROM memory_shadow_learning_decisions").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT count(*) FROM memory_observations").fetchone()[0])

    def test_queued_evaluation_yields_to_new_interactive_turn(self):
        turn_id, _ = self.turn("Eine möglicherweise dauerhafte Information.")
        fake = FakeLearningLLM(proposal())
        pipeline = ShadowLearningPipeline(self.database, fake)
        queued_generation = pipeline.priority_token()
        pipeline.prioritize_interactive_turn()
        result = pipeline.evaluate_turn(turn_id, queued_generation)
        self.assertEqual("undetermined", result["decision_type"])
        self.assertEqual("interactive_priority", result["reason_code"])
        self.assertEqual(0, fake.calls)

    def test_report_is_bounded_and_contains_performance(self):
        turn_id, _ = self.turn("Nur eine Begrüßung ohne bleibende Information.")
        fake = FakeLearningLLM(proposal(decision="no_persist"))
        pipeline = ShadowLearningPipeline(self.database, fake)
        pipeline.evaluate_turn(turn_id)
        report = pipeline.report()
        self.assertEqual(1, report["turns_evaluated"])
        self.assertEqual(1, report["decisions"]["no_persist"])
        self.assertEqual(0, report["user_visible_latency_added_ms"])
        self.assertNotIn("Begrüßung", json.dumps(report, ensure_ascii=False))


class ShadowLearningMigrationTest(unittest.TestCase):
    @staticmethod
    def create_v9(path):
        database = EveDatabase(path)
        with database.connect() as connection:
            connection.execute("DROP TABLE memory_shadow_decision_observations")
            connection.execute("DROP TABLE memory_shadow_learning_decisions")
            connection.execute("PRAGMA user_version=9")

    def test_v9_upgrade_creates_backup_and_shadow_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "eve.db"
            self.create_v9(path)
            database = EveDatabase(path)
            backups = list((path.parent / "backups").glob(f"eve-schema-v9-to-v{SCHEMA_VERSION}-*.db"))
            self.assertEqual(1, len(backups))
            with database.connect() as connection:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                self.assertIn("memory_shadow_learning_decisions", tables)
                self.assertIn("memory_shadow_decision_observations", tables)
                self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
            with sqlite3.connect(backups[0]) as backup:
                self.assertEqual(9, backup.execute("PRAGMA user_version").fetchone()[0])

    def test_failed_v10_upgrade_rolls_back(self):
        class BrokenDatabase(EveDatabase):
            @classmethod
            def _migrations(cls):
                migrations = dict(EveDatabase._migrations())
                def broken(connection):
                    EveDatabase._migrate_v9_to_v10(connection)
                    raise RuntimeError("v10 broken")
                migrations[9] = broken
                return migrations

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.db"
            self.create_v9(path)
            with self.assertRaisesRegex(RuntimeError, "v10 broken"):
                BrokenDatabase(path)
            with sqlite3.connect(path) as connection:
                self.assertEqual(9, connection.execute("PRAGMA user_version").fetchone()[0])
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='memory_shadow_learning_decisions'"
                ).fetchone())
                self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
