import unittest

from app.core.api_source import APISource


class _ConvStore:
    active_id = "conv_api_1"


class TestAPISourceMessageProjection(unittest.TestCase):
    def test_signal_messages_have_unique_ids_and_ordinals(self):
        source = object.__new__(APISource)
        source.conv_store = _ConvStore()

        first = source.build_message_for_signal(
            role="user",
            content="hello",
            index=0,
            timestamp=100.0,
        )
        second = source.build_message_for_signal(
            role="assistant",
            content="world",
            index=1,
            timestamp=101.0,
        )

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["conversation_id"], "conv_api_1")
        self.assertEqual(second["conversation_id"], "conv_api_1")
        self.assertEqual(first["ordinal"], 0)
        self.assertEqual(second["ordinal"], 1)
        self.assertTrue(first["content_hash"])
        self.assertTrue(second["content_hash"])

