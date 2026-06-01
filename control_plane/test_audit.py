#!/usr/bin/env python3
"""
Testes de auditoria avançada para thread safety no SQLite.
"""

import os
import tempfile
import threading
import unittest

from database import TelemetryDB


class TestTelemetryDBThreadSafety(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self.db = TelemetryDB(self.db_path)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_concurrent_inserts(self):
        thread_count = 5
        inserts_per_thread = 50
        exceptions = []
        exceptions_lock = threading.Lock()

        def worker(worker_id: int) -> None:
            try:
                for i in range(inserts_per_thread):
                    self.db.insert_report(
                        switch_id=worker_id + 1,
                        port_id=i,
                        metric_type=0,
                        metric_value=100 + i,
                        switch_timestamp=1000 + i,
                    )
            except Exception as exc:  # noqa: BLE001 - teste deve falhar se ocorrer erro
                with exceptions_lock:
                    exceptions.append(exc)

        threads = [
            threading.Thread(target=worker, args=(idx,))
            for idx in range(thread_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if exceptions:
            self.fail(f"Exceção durante inserts concorrentes: {exceptions[0]}")

        total_expected = thread_count * inserts_per_thread
        metrics = self.db.get_latest_metrics(metric_type=0, limit=total_expected + 10)
        self.assertEqual(len(metrics), total_expected)


if __name__ == "__main__":
    unittest.main()
