import ast
import inspect
import tempfile
import unittest
from pathlib import Path

from eve_agent.minimal import CORE_PROMPT, NativeToolRuntime
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.storage import EveDatabase


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "eve_agent"


class PythonSemanticsBoundaryTest(unittest.TestCase):
    def test_no_bundled_or_file_backed_memory_content_exists(self):
        forbidden = (
            ROOT / "memory" / "facts.md",
            ROOT / "memory" / "aliases.md",
            ROOT / "memory" / "reminders.json",
            SOURCE / "resources" / "home_assistant_language_de.json",
        )
        self.assertTrue(all(not path.exists() for path in forbidden))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            EveDatabase(root / "data" / "eve.db")
            self.assertFalse((root / "memory").exists())

    def test_productive_python_has_no_semantic_dictionary_declarations(self):
        suspicious_names = {
            "stopwords", "synonyms", "intent_keywords", "intent_phrases",
            "domain_terms", "device_terms", "room_terms", "concepts",
        }
        findings = []
        for path in SOURCE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id.casefold().lstrip("_") in suspicious_names:
                        findings.append(f"{path.name}:{target.lineno}:{target.id}")
        self.assertEqual([], findings)

    def test_core_prompt_is_small_and_has_no_household_examples(self):
        contract = CORE_PROMPT.casefold()
        self.assertLess(len(CORE_PROMPT.split()), 50)
        for term in ("rollladen", "lampe", "wohnzimmer", "garage", "carport"):
            self.assertNotIn(term, contract)

    def test_predecision_provider_retrieval_contains_no_domain_semantics(self):
        source = inspect.getsource(MemoryV2Runtime.provider_context_claims).casefold()
        for term in ("automation", "light", "cover", "rollladen", "rollo"):
            self.assertNotIn(term, source)
        planner = (SOURCE / "minimal.py").read_text(encoding="utf-8")
        self.assertNotIn("messages, 700,", planner)

    def test_initial_capability_index_contains_no_prompt_prose_or_argument_contracts(self):
        index = NativeToolRuntime._capability_index({
            "provider": {
                "description": "semantic prose must stay out of the initial turn",
                "operations": {
                    "operation": {
                        "effect": "read", "purpose": "more prose",
                        "parameters_schema": {"type": "object", "properties": {
                            "query": {"type": "string"},
                        }},
                    },
                },
            },
        }, "arbitrary user text")
        self.assertEqual(
            {"provider": {"operations": {"operation": {"effect": "read"}}}},
            index,
        )

    def test_capability_publication_does_not_depend_on_user_words(self):
        capabilities = {
            "alpha": {"description": "provider", "operations": {"read": {"effect": "read"}}},
            "beta": {"description": "provider", "operations": {"write": {"effect": "write"}}},
        }
        self.assertEqual(
            NativeToolRuntime._capability_index(capabilities, "first arbitrary text"),
            NativeToolRuntime._capability_index(capabilities, "completely different input"),
        )

    def test_memory_evidence_is_not_ranked_by_python_word_overlap(self):
        source = (SOURCE / "minimal.py").read_text(encoding="utf-8")
        self.assertNotIn("_relevant_evidence", source)
        self.assertNotIn("_catalog_tokens", source)
        self.assertNotIn("query_tokens", source)

    def test_python_contains_no_language_specific_speech_rewriter(self):
        source = (SOURCE / "llm.py").read_text(encoding="utf-8")
        self.assertNotIn("_german_integer", source)
        self.assertNotIn("_spell_numbers_for_speech", source)
        self.assertNotIn("_normalize_spoken_units", source)

    def test_provider_states_have_no_bundled_language_translation_table(self):
        source = (SOURCE / "home_assistant.py").read_text(encoding="utf-8")
        for mapping in (
            '"on": "an"', '"off": "aus"', '"locked": "abgeschlossen"',
            '"unlocked": "aufgeschlossen"', '"turn_on": "eingeschaltet"',
            '"turn_off": "ausgeschaltet"',
        ):
            self.assertNotIn(mapping, source)

    def test_runtime_contains_no_deterministic_semantic_router_or_effect_guess(self):
        shadow = (SOURCE / "shadow_learning.py").read_text(encoding="utf-8")
        compiler = (SOURCE / "memory_compiler.py").read_text(encoding="utf-8")
        self.assertNotIn("_grounded_provider_binding", shadow)
        self.assertNotIn("name.startswith((\"get_\"", compiler)
        self.assertNotIn("name.startswith(('get_'", compiler)

    def test_runtime_has_no_executable_memory_action_bridge(self):
        source = (SOURCE / "minimal.py").read_text(encoding="utf-8")
        self.assertNotIn("_execute_memory_action", source)
        self.assertNotIn("memory_action", source)
        self.assertNotIn("resolve_planning_call", source)
        self.assertNotIn("home_assistant.discover", source)
        self.assertNotIn("home_assistant.list_entities", source)
        self.assertNotIn("action_candidates_for_query", source)
        self.assertNotIn("learned_actions", source)

    def test_home_assistant_is_a_native_transport_without_parallel_mcp(self):
        runtime = (SOURCE / "minimal.py").read_text(encoding="utf-8")
        provider = (SOURCE / "home_assistant.py").read_text(encoding="utf-8")
        self.assertNotIn("home_assistant_mcp", runtime)
        self.assertNotIn("upsert_automation", provider)
        self.assertNotIn("execute_plan", provider)
        self.assertNotIn("resolve_planning_call", provider)


if __name__ == "__main__":
    unittest.main()
