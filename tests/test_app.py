import tempfile
import queue
import unittest
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from dje_finder.config import Config
from dje_finder.persistence import IndexManager, StateManager, init_db, get_db_connection
from dje_finder.network import DownloadManager, PDFDiscovery
from dje_finder.worker import WorkerController

class FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temporary_directory.name)
        self.config_patchers = [
            patch.object(Config, "BASE_DIR", self.base_dir),
            patch.object(Config, "INDEX_FILE", self.base_dir / "indice.json"),
            patch.object(Config, "STATE_FILE", self.base_dir / "estado.json"),
            patch.object(Config, "DB_FILE", self.base_dir / "dje_finder.db"),
        ]
        for patcher in self.config_patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.config_patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def test_index_is_saved_and_loaded(self):
        manager = IndexManager()
        manager.add_pdf("20260102")
        manager.save()

        loaded_manager = IndexManager()
        self.assertEqual(loaded_manager.data["pdfs"], ["20260102"])

    def test_state_recognizes_in_progress_work(self):
        manager = StateManager()
        manager.data["em_andamento"] = ["20260102"]
        manager.save()

        self.assertTrue(StateManager().has_valid_state())

    def test_valid_pdf_replaces_partial_file(self):
        response = FakeResponse([b"%PDF-1.7\n", b"content"])

        result = DownloadManager.save_pdf(response, "20260102")

        target = self.base_dir / "2026" / "dpj-20260102.pdf"
        self.assertTrue(result)
        self.assertEqual(target.read_bytes(), b"%PDF-1.7\ncontent")
        self.assertFalse(target.with_suffix(".pdf.part").exists())
        self.assertTrue(response.closed)

    def test_invalid_content_is_rejected(self):
        response = FakeResponse([b"<html>not found</html>"])

        result = DownloadManager.save_pdf(response, "20260102")

        target = self.base_dir / "2026" / "dpj-20260102.pdf"
        self.assertIsInstance(result, ValueError)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix(".pdf.part").exists())
        self.assertTrue(response.closed)

    def test_existing_pdf_is_discovered_from_disk(self):
        target = self.base_dir / "2026" / "dpj-20260102.pdf"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"%PDF-1.7\nbackup")

        manager = IndexManager()
        discovered_dates = manager.scan_existing_pdfs()

        self.assertEqual(discovered_dates, {"20260102"})
        self.assertEqual(manager.data["pdfs"], ["20260102"])

    def test_build_queue_skips_existing_backup_pdf(self):
        target = self.base_dir / "2026" / "dpj-20260102.pdf"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"%PDF-1.7\nbackup")

        with patch.object(Config, "START_DATE", "20260101"):
            index_manager = IndexManager()
            state_manager = StateManager()
            worker = WorkerController(index_manager, state_manager, queue.Queue())
            worker.build_queue()

        self.assertIn("20260102", index_manager.data["pdfs"])
        self.assertNotIn("20260102", worker.fila)
        self.assertEqual(state_manager.data["baixados"], 1)

    def test_imported_backup_advances_last_indexed_date(self):
        today = datetime.today().strftime("%Y%m%d")
        target = self.base_dir / today[:4] / f"dpj-{today}.pdf"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"%PDF-1.7\nbackup")

        index_manager = IndexManager()
        state_manager = StateManager()
        worker = WorkerController(index_manager, state_manager, queue.Queue())
        worker.build_queue()

        self.assertEqual(index_manager.data["ultima_data_indexada"], today)
        self.assertEqual(worker.fila, [])

    def test_saved_queue_before_imported_backup_is_discarded(self):
        today = datetime.today().strftime("%Y%m%d")
        backup = self.base_dir / today[:4] / f"dpj-{today}.pdf"
        backup.parent.mkdir(parents=True)
        backup.write_bytes(b"%PDF-1.7\nbackup")

        index_manager = IndexManager()
        state_manager = StateManager()
        state_manager.data["fila_restante"] = ["20030104", "20170228"]
        state_manager.save() # Persiste na tabela state do SQLite
        
        worker = WorkerController(index_manager, state_manager, queue.Queue())
        worker.build_queue()

        self.assertEqual(index_manager.data["ultima_data_indexada"], today)
        self.assertEqual(worker.fila, [])
        self.assertEqual(state_manager.data["atualizaveis"], 0)

    def test_large_gap_between_imported_pdfs_is_queued(self):
        for date_str in ["20051230", "20070102"]:
            target = self.base_dir / date_str[:4] / f"dpj-{date_str}.pdf"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"%PDF-1.7\nbackup")

        index_manager = IndexManager()
        missing_dates = index_manager.find_missing_gap_dates({"20051230", "20070102"})

        self.assertIn("20060101", missing_dates)
        self.assertIn("20061231", missing_dates)

    def test_build_queue_includes_large_backup_gap(self):
        class FixedDateTime(datetime):
            @classmethod
            def today(cls):
                return cls(2007, 1, 2)

        for date_str in ["20051230", "20070102"]:
            target = self.base_dir / date_str[:4] / f"dpj-{date_str}.pdf"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"%PDF-1.7\nbackup")

        with patch.object(Config, "START_DATE", "20030103"):
            with patch("dje_finder.persistence.datetime", FixedDateTime):
                index_manager = IndexManager()
                state_manager = StateManager()
                worker = WorkerController(index_manager, state_manager, queue.Queue())
                worker.build_queue()

        self.assertIn("20060101", worker.fila)
        self.assertIn("20061231", worker.fila)
        self.assertEqual(state_manager.data["baixados"], 2)

    def test_scan_reports_initial_progress(self):
        target = self.base_dir / "2026" / "dpj-20260102.pdf"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"%PDF-1.7\nbackup")
        progress_events = []

        manager = IndexManager()
        manager.scan_existing_pdfs(
            lambda phase, current, total, found: progress_events.append((phase, current, total, found))
        )

        self.assertEqual(progress_events[0], ("scan", 0, 1, 0))
        self.assertEqual(progress_events[-1], ("scan", 1, 1, 1))

    def test_missing_indexed_pdf_is_queued_for_repair(self):
        index_manager = IndexManager()
        index_manager.data["pdfs"] = ["20260102"]
        index_manager.save()
        
        state_manager = StateManager()
        worker = WorkerController(index_manager, state_manager, queue.Queue())
        worker.build_queue()

        self.assertIn("20260102", worker.fila)

    def test_missing_indexed_year_folder_is_queued_for_repair(self):
        index_manager = IndexManager()
        index_manager.data["pdfs"] = ["20250102", "20250103"]
        index_manager.save()
        
        state_manager = StateManager()
        worker = WorkerController(index_manager, state_manager, queue.Queue())
        worker.build_queue()

        self.assertIn("20250102", worker.fila)
        self.assertIn("20250103", worker.fila)

    def test_verified_absent_date_is_not_requeued(self):
        index_manager = IndexManager()
        index_manager.add_absent_date("20250102")
        state_manager = StateManager()
        worker = WorkerController(index_manager, state_manager, queue.Queue())
        worker.build_queue()

        self.assertNotIn("20250102", worker.fila)

    def test_pdf_removes_date_from_absent_list(self):
        index_manager = IndexManager()
        index_manager.add_absent_date("20250102")
        index_manager.add_pdf("20250102")

        self.assertIn("20250102", index_manager.data["pdfs"])
        self.assertNotIn("20250102", index_manager.data["datas_sem_pdf"])

    def test_automatic_migration_from_json_to_sqlite(self):
        # 1. Cria arquivos JSON antigos
        old_index = {
            "ultima_data_indexada": "20260105",
            "pdfs": ["20260101", "20260102"],
            "datas_sem_pdf": ["20260103", "20260104"]
        }
        old_state = {
            "fila_restante": ["20260106", "20260107"],
            "baixados": 2
        }
        
        with open(Config.INDEX_FILE, 'w', encoding='utf-8') as f:
            json.dump(old_index, f)
        with open(Config.STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(old_state, f)
            
        # 2. Inicializa o banco de dados e migra
        init_db()
        
        # 3. Verifica se os arquivos originais foram renomeados/movidos para backup (.bak)
        self.assertFalse(Config.INDEX_FILE.exists())
        self.assertTrue(Config.INDEX_FILE.with_suffix(".json.bak").exists())
        self.assertFalse(Config.STATE_FILE.exists())
        self.assertTrue(Config.STATE_FILE.with_suffix(".json.bak").exists())
        
        # 4. Carrega e valida os dados importados no SQLite
        index_mgr = IndexManager()
        state_mgr = StateManager()
        
        self.assertEqual(index_mgr.data["ultima_data_indexada"], "20260105")
        self.assertEqual(index_mgr.data["pdfs"], ["20260101", "20260102"])
        self.assertEqual(index_mgr.data["datas_sem_pdf"], ["20260103", "20260104"])
        
        state_mgr.load()
        self.assertEqual(state_mgr.data["fila_restante"], ["20260106", "20260107"])
        self.assertEqual(state_mgr.data["baixados"], 2)


class SyncBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temporary_directory.name)
        self.config_patchers = [
            patch.object(Config, "BASE_DIR", self.base_dir),
            patch.object(Config, "INDEX_FILE", self.base_dir / "indice.json"),
            patch.object(Config, "STATE_FILE", self.base_dir / "estado.json"),
            patch.object(Config, "DB_FILE", self.base_dir / "dje_finder.db"),
        ]
        for patcher in self.config_patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.config_patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    @patch("socket.create_connection")
    @patch("dje_finder.worker.requests.get")
    def test_portal_offline_prevents_online_sync(self, mock_get, mock_create_connection):
        mock_create_connection.return_value = unittest.mock.Mock()
        def side_effect(url, *args, **kwargs):
            mock_res = unittest.mock.Mock()
            if "google.com" in url:
                mock_res.status_code = 200
                return mock_res
            else:
                mock_res.status_code = 502
                return mock_res
        mock_get.side_effect = side_effect
        
        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)
        
        worker.running = True
        worker._check_and_run_sync("2 - Rápido (5MB/s)")
        
        msg1 = gui_queue.get_nowait()
        self.assertEqual(msg1["type"], "checking_connection")
        msg2 = gui_queue.get_nowait()
        self.assertEqual(msg2["type"], "connection_error")
        self.assertEqual(msg2["error_type"], "portal")
        
        self.assertFalse(worker.running)
        self.assertIsNone(worker.executor)

    @patch("socket.create_connection")
    @patch("dje_finder.worker.requests.get")
    def test_internet_offline_prevents_online_sync(self, mock_get, mock_create_connection):
        import requests
        mock_create_connection.side_effect = OSError("No internet connection")
        mock_get.side_effect = requests.RequestException("No internet")
        
        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)
        
        worker.running = True
        worker._check_and_run_sync("2 - Rápido (5MB/s)")
        
        msg1 = gui_queue.get_nowait()
        self.assertEqual(msg1["type"], "checking_connection")
        msg2 = gui_queue.get_nowait()
        self.assertEqual(msg2["type"], "connection_error")
        self.assertEqual(msg2["error_type"], "internet")
        
        self.assertFalse(worker.running)
        self.assertIsNone(worker.executor)

    @patch("socket.create_connection")
    @patch("dje_finder.worker.requests.get")
    @patch("dje_finder.worker.WorkerController.process_date")
    def test_portal_online_allows_sync(self, mock_process_date, mock_get, mock_create_connection):
        mock_create_connection.return_value = unittest.mock.Mock()
        mock_process_date.return_value = ("BAIXADO", "20260102", None)
        mock_res = unittest.mock.Mock()
        mock_res.status_code = 200
        mock_get.return_value = mock_res
        
        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)
        worker.fila = ["20260102"]
        
        worker.running = True
        worker._check_and_run_sync("2 - Rápido (5MB/s)")
        
        msg1 = gui_queue.get_nowait()
        self.assertEqual(msg1["type"], "checking_connection")
        self.assertIsNotNone(worker.executor)
        executor = worker.executor
        worker.finish()
        if executor:
            executor.shutdown(wait=True)

    @patch("dje_finder.network.PDFDiscovery.get_session")
    def test_portal_error_does_not_save_absent_date(self, mock_get_session):
        import requests
        mock_session = unittest.mock.Mock()
        mock_response = unittest.mock.Mock()
        mock_response.status_code = 502
        mock_response.raise_for_status.side_effect = requests.HTTPError("502 Bad Gateway")
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session
        
        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)
        
        status, date_str, err = worker.process_date("20260102")
        
        self.assertEqual(status, "ERRO")
        self.assertIsInstance(err, requests.HTTPError)
        
        future = unittest.mock.Mock()
        future.result.return_value = (status, date_str, err)
        worker.active_futures.add(future)
        worker.active_dates.add(date_str)
        worker.future_done(future, date_str)
        
        self.assertIn("20260102", state_manager.data["falhas"])
        self.assertNotIn("20260102", index_manager.data["datas_sem_pdf"])

    @patch("dje_finder.network.PDFDiscovery.get_session")
    def test_404_records_absent_date(self, mock_get_session):
        mock_session = unittest.mock.Mock()
        mock_response = unittest.mock.Mock()
        mock_response.status_code = 404
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session
        
        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)
        
        status, date_str, err = worker.process_date("20260102")
        
        self.assertEqual(status, "NAO_ENCONTRADO")
        self.assertIsNone(err)
        
        future = unittest.mock.Mock()
        future.result.return_value = (status, date_str, err)
        worker.active_futures.add(future)
        worker.active_dates.add(date_str)
        worker.future_done(future, date_str)
        
        self.assertIn("20260102", index_manager.data["datas_sem_pdf"])
        self.assertNotIn("20260102", state_manager.data["falhas"])

    @patch("socket.create_connection")
    @patch("dje_finder.worker.requests.get")
    def test_local_check_works_when_portal_offline(self, mock_get, mock_create_connection):
        import requests
        mock_create_connection.side_effect = OSError("No internet")
        mock_get.side_effect = requests.RequestException("No internet")
        
        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)
        
        worker.build_queue()
        self.assertEqual(worker.fila, [])

    def test_consecutive_errors_pause_sync(self):
        import requests
        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)
        worker.running = True
        worker.executor = unittest.mock.Mock()
        worker.fila = ["20260102", "20260103", "20260104", "20260105", "20260106"]
        
        for i in range(5):
            date_str = worker.fila.pop(0)
            future = unittest.mock.Mock()
            future.result.return_value = ("ERRO", date_str, requests.RequestException("Timeout"))
            worker.active_futures.add(future)
            worker.active_dates.add(date_str)
            worker.future_done(future, date_str)
            
        self.assertTrue(worker.paused)
        msgs = []
        try:
            while True:
                msgs.append(gui_queue.get_nowait())
        except queue.Empty:
            pass
            
        types = [m["type"] for m in msgs]
        self.assertIn("portal_unstable", types)


if __name__ == "__main__":
    unittest.main()
