import json
import unittest
from pathlib import Path

from digos_lib.constants import DIGOS_DIR, MASTER_DIR
from factory.manager import FactoryManager
from factory.superior import SuperiorAgent


class TestEmbeddedFactoryRuntime(unittest.TestCase):
    def test_clean_clone_exposes_executable_factory_contract(self):
        root = Path(MASTER_DIR)
        self.assertTrue((root / "factory" / "manager.py").exists())
        self.assertTrue((root / "factory" / "superior.py").exists())

    def test_factory_accepts_capability_request_without_claiming_tool_ready(self):
        manager = FactoryManager()
        manager.setup()

        result = manager.request_new_capability(
            capability_id="stt_audio_input",
            family="VOICE",
            description="Allow DIGOS to receive voice messages",
            tool_name="speech_to_text",
            requested_by="test",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "accepted_for_factory_review")
        self.assertEqual(result["generated_code"], "")
        self.assertFalse(result["code_validated"])

        ticket_path = DIGOS_DIR / "factory" / "tickets" / f"{result['ticket_id']}.json"
        self.assertTrue(ticket_path.exists())
        ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        self.assertEqual(ticket["capability_id"], "stt_audio_input")
        self.assertEqual(ticket["tool_name"], "speech_to_text")

    def test_superior_agent_can_create_internal_builder(self):
        superior = SuperiorAgent()
        agent = superior.create_internal(
            agent_type="builder",
            mode="collaborative",
            name="voice_builder",
            mission="Prepare voice input capability",
        )

        self.assertEqual(agent.name, "voice_builder")
        self.assertIn("voice_builder", superior.internal_agents)
        self.assertGreaterEqual(len(agent.get_capabilities()), 1)


if __name__ == "__main__":
    unittest.main()
