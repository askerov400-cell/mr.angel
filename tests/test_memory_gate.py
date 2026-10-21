import unittest
from database import select_backend
from x2pos import dialogue
from memory import service


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

class StatusReportTests(unittest.TestCase):
    def test_report_names_the_blocker(self):
        report = service.status_report({'memory_status': 'saved', 'business_until': 100.0,
                                        'document_context': {'text':'x'}}, 'supabase', now=40.0)
        self.assertIn('backend=supabase', report)
        self.assertIn('Последний статус записи: saved', report)
        self.assertIn('активно ещё 60', report)
        self.assertIn('Файл в контексте: да', report)

    def test_report_without_window_or_file(self):
        report = service.status_report({'memory_status': 'ignored'}, 'sqlite', now=10.0)
        self.assertIn('Бизнес-окно: нет', report)
        self.assertIn('Файл в контексте: нет', report)
        self.assertIn('backend=sqlite', report)
