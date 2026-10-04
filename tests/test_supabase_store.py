import unittest
from unittest.mock import patch

from storage import supabase_store as store


class SupabaseStoreTests(unittest.TestCase):
    def test_read_is_scoped_and_paginates(self):
        with patch.object(store, "_request", side_effect=[
            [{"id": 1, "telegram_user_id": 12}], [],
        ]) as request:
            self.assertEqual(store.get_facts(12)[0]["id"], 1)
            for call in request.call_args_list:
                self.assertEqual(call.args[1]["telegram_user_id"], "eq.12")
            self.assertEqual(request.call_args_list[1].args[1]["offset"], "1")

    def test_wrong_user_response_is_rejected(self):
        with patch.object(store, "_request", return_value=[{"telegram_user_id": 13}]):
            with self.assertRaises(store.StorageError):
                store.get_facts(12)

    def test_insert_requires_database_confirmation(self):
        with patch.object(store, "_request", return_value=[]):
            with self.assertRaises(store.StorageError):
                store.add_fact(12, "test", "A fact")

    def test_invalid_owner_and_confidence_never_reach_network(self):
        with patch.object(store, "_request") as request:
            for user_id in (0, -1, True, "12"):
                with self.assertRaises(ValueError):
                    store.get_facts(user_id)
            with self.assertRaises(ValueError):
                store.add_fact(12, "test", "A fact", confidence=float("nan"))
            request.assert_not_called()

    def test_failure_does_not_disclose_response_body(self):
        from urllib.error import HTTPError
        with patch.dict("os.environ", {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_test",
        }), patch.object(store, "urlopen", side_effect=HTTPError(
            "https://example.supabase.co", 401, "private response", {}, None,
        )):
            with self.assertRaises(store.StorageError) as caught:
                store.init_database()
            self.assertEqual(str(caught.exception), "Supabase request failed (HTTP 401)")


if __name__ == "__main__":
    unittest.main()
