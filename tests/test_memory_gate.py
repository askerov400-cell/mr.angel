import unittest
from database import select_backend
from x2pos import dialogue


class BackendSelectionTests(unittest.TestCase):
    def test_explicit_backend_wins(self):
        self.assertEqual(select_backend({'MEMORY_BACKEND': 'sqlite'}.get), 'sqlite')
        self.assertEqual(select_backend({'MEMORY_BACKEND': 'SUPABASE'}.get), 'supabase')

    def test_credentials_enable_supabase_without_variable(self):
        env = {'SUPABASE_URL': 'https://x.supabase.co', 'SUPABASE_SECRET_KEY': 'sb_secret_x'}
        self.assertEqual(select_backend(env.get), 'supabase')

    def test_no_credentials_fall_back_to_sqlite(self):
        self.assertEqual(select_backend({}.get), 'sqlite')
        self.assertEqual(select_backend({'SUPABASE_URL': 'https://x.supabase.co'}.get), 'sqlite')


class BusinessGateTests(unittest.TestCase):
    def test_business_requests_are_recognised(self):
        for text in ('покажи продажи за месяц', 'сколько выручка', 'X2POS за неделю'):
            self.assertTrue(dialogue.is_request(text), text)

    def test_personal_messages_are_not_business(self):
        for text in ('почему ты не запоминаешь разговор', 'как дела', 'что ты умеешь'):
            self.assertFalse(dialogue.is_request(text), text)


if __name__ == '__main__':
    unittest.main()
