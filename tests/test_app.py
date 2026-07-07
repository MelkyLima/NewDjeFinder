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
from dje_finder.indexer import PDFIndexer
from dje_finder.search import (
    MATCH_EXACT_PHRASE,
    MATCH_NEAR_CONTEXT,
    PDFSearchEngine,
    clean_snippet,
    normalize_fts_phrase_query,
    normalize_fts_query,
)

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
            with patch("dje_finder.worker.datetime", FixedDateTime):
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

    def test_local_scan_works_without_portal(self):
        """build_queue é operação local e não depende de rede; deve concluir sem exceção."""
        # Cria um PDF local para que o scan encontre algo
        target = self.base_dir / "2026" / "dpj-20260110.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.7\nconteudo")

        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)

        # Não deve lançar exceção mesmo sem internet
        try:
            worker.build_queue()
            built_ok = True
        except Exception:
            built_ok = False

        self.assertTrue(built_ok)
        # O PDF local deve ser reconhecido e não entrar na fila
        self.assertNotIn("20260110", worker.fila)
        self.assertIn("20260110", index_manager.data["pdfs"])

    def test_consecutive_errors_pause_sync(self):
        import requests
        index_manager = IndexManager()
        state_manager = StateManager()
        gui_queue = queue.Queue()
        worker = WorkerController(index_manager, state_manager, gui_queue)
        worker.running = True
        worker.executor = unittest.mock.Mock()

        # Pré-popula 5 datas diretamente nas estruturas internas (sem build_queue)
        dates = ["20260102", "20260103", "20260104", "20260105", "20260106"]
        state_manager.data["baixados"] = 0
        state_manager.data["localizados"] = len(dates)
        state_manager.data["atualizaveis"] = len(dates)

        for date_str in dates:
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


class IndexerTests(unittest.TestCase):
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
        init_db()

    def tearDown(self):
        for patcher in reversed(self.config_patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def create_mock_pdf(self, date_str, pages_content):
        import fitz
        year = date_str[:4]
        pdf_dir = self.base_dir / year
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"dpj-{date_str}.pdf"
        
        doc = fitz.open()
        for text in pages_content:
            page = doc.new_page()
            page.insert_text((50, 50), text)
        doc.save(pdf_path)
        doc.close()
        return pdf_path

    def test_indexer_extracts_and_saves_content_in_fts5(self):
        date_str = "20260101"
        content_p1 = "Esta e a comarca de Boa Vista no Estado de Roraima."
        content_p2 = "Decisão judicial deferida pelo magistrado competente."
        self.create_mock_pdf(date_str, [content_p1, content_p2])

        indexer = PDFIndexer()
        success = indexer.index_pdf(date_str)
        self.assertTrue(success)

        # Valida no banco de dados SQLite
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Valida tabela indexed_pdfs
        cursor.execute("SELECT status, error_message FROM indexed_pdfs WHERE date_str = ?", (date_str,))
        status_row = cursor.fetchone()
        self.assertIsNotNone(status_row)
        self.assertEqual(status_row["status"], "SUCCESS")
        self.assertIsNone(status_row["error_message"])

        # 2. Valida busca FTS5 (busca case-insensitive e acentos ignorados)
        cursor.execute("SELECT date_str, content FROM pdf_pages_fts WHERE pdf_pages_fts MATCH 'decisao'")
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)
        # Schema v2: texto de todas as páginas concatenado em uma única linha
        self.assertIn("Decisão", rows[0]["content"])
        self.assertIn("comarca", rows[0]["content"])  # texto da página 1 também está presente
        
        # 3. Valida estatísticas
        stats = indexer.get_stats()
        self.assertEqual(stats["total_indexados"], 1)
        # Schema v2: 1 linha por PDF (não por página)
        self.assertEqual(stats["total_paginas"], 1)
        
        conn.close()

    def test_indexer_is_incremental_and_idempotent(self):
        date_str = "20260102"
        self.create_mock_pdf(date_str, ["Original text page 1"])
        
        indexer = PDFIndexer()
        
        # Registra o PDF na tabela pdfs de antemão
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO pdfs (date_str) VALUES (?)", (date_str,))
        conn.commit()
        conn.close()

        # Primeira indexação
        self.assertTrue(indexer.index_pdf(date_str))
        
        # Segunda indexação do mesmo PDF (deve limpar o anterior e reinserir sem duplicar)
        self.assertTrue(indexer.index_pdf(date_str))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM pdf_pages_fts WHERE date_str = ?", (date_str,))
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1) # Não deve ter 2 registros duplicados!
        conn.close()

    def test_indexer_handles_corrupted_pdf_resiliently(self):
        date_str = "20260103"
        # Cria arquivo físico mas com conteúdo inválido (lixo)
        year = date_str[:4]
        pdf_dir = self.base_dir / year
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"dpj-{date_str}.pdf"
        pdf_path.write_bytes(b"Lixo corrompido que nao e PDF")

        indexer = PDFIndexer()
        success = indexer.index_pdf(date_str)
        self.assertFalse(success) # Deve retornar False

        # Valida que o erro foi gravado no status
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, error_message FROM indexed_pdfs WHERE date_str = ?", (date_str,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "FAILED")
        self.assertIsNotNone(row["error_message"])
        conn.close()

    def test_indexer_parallel_indexing_does_not_corrupt_database(self):
        # 1. Cria 10 PDFs fictícios
        dates = [f"202602{i:02d}" for i in range(1, 11)]
        for date_str in dates:
            self.create_mock_pdf(date_str, [f"Texto do PDF de data {date_str} na pagina 1"])

        # 2. Registra na tabela pdfs
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.executemany("INSERT INTO pdfs (date_str) VALUES (?)", [(d,) for d in dates])
        conn.commit()
        conn.close()

        # 3. Executa indexação em paralelo (4 workers concorrentes escrevendo no SQLite com WAL)
        indexer = PDFIndexer()
        indexed_count = indexer.index_all_pending(max_workers=4)
        self.assertEqual(indexed_count, 10)

        # 4. Valida se todos foram indexados
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM indexed_pdfs WHERE status = 'SUCCESS'")
        self.assertEqual(cursor.fetchone()[0], 10)
        
        cursor.execute("SELECT COUNT(*) FROM pdf_pages_fts")
        self.assertEqual(cursor.fetchone()[0], 10)
        conn.close()


class SearchTests(unittest.TestCase):
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
        init_db()

        conn = get_db_connection()
        cursor = conn.cursor()
        rows = [
            ("20240115", "Decisao judicial sobre Boa Vista e comarca estadual."),
            ("20240220", "Despacho ordinario sem o termo principal."),
            ("20250110", "Nova decisao publicada na comarca de Pacaraima."),
            ("20250305", "Decisao recente com prioridade de julgamento."),
            ("20250408", "Pereira compareceu antes de outros nomes; Lima aparece depois."),
            ("20250409", "Lima Pereira assinou o pedido."),
            ("20260111", "Resolve elogiar servidores como reconhecimento. Melquizedeque Lima Pereira recebeu a mencao."),
            ("20260112", "Resolve elogiar servidores nesta portaria. " + ("texto distante " * 80) + "Melquizedeque Lima Pereira recebeu a mencao."),
        ]
        cursor.executemany("INSERT INTO pdfs (date_str) VALUES (?)", [(date,) for date, _ in rows])
        cursor.executemany(
            "INSERT INTO pdf_pages_fts (date_str, content) VALUES (?, ?)",
            rows,
        )
        cursor.executemany(
            "INSERT INTO indexed_pdfs (date_str, indexed_at, status, error_message) VALUES (?, ?, ?, ?)",
            [(date, "2026-01-01T00:00:00", "SUCCESS", None) for date, _ in rows[:3]],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        for patcher in reversed(self.config_patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def test_normalize_fts_query_keeps_user_terms_safe(self):
        self.assertEqual(normalize_fts_query('decisao: "boa vista"'), '"decisao" "boa" "vista"')
        self.assertEqual(normalize_fts_phrase_query('Lima, Pereira!'), '"Lima Pereira"')

    def test_clean_snippet_compacts_to_one_line(self):
        snippet = clean_snippet("Antes\n\n[termo]\t encontrado   depois", max_length=25)

        self.assertEqual(snippet, "Antes [termo] encontra...")

    def test_search_returns_paginated_results_and_counts(self):
        engine = PDFSearchEngine(page_size=2)
        response = engine.search("decisao", offset=0)

        self.assertEqual(response.total, 3)
        self.assertEqual(len(response.results), 2)
        self.assertTrue(response.has_more)
        self.assertEqual(response.year_counts["2025"], 2)
        self.assertEqual(response.year_counts["2024"], 1)
        self.assertTrue(response.has_pending_indexing)
        self.assertIn("dpj-", response.results[0].pdf_path.name)

    def test_search_filters_by_year_and_month(self):
        engine = PDFSearchEngine()
        response = engine.search("decisao", year="2025", month="03")

        self.assertEqual(response.total, 1)
        self.assertEqual(response.results[0].date_str, "20250305")
        self.assertEqual(response.month_counts, {"01": 1, "03": 1})

    def test_search_orders_by_oldest(self):
        engine = PDFSearchEngine()
        response = engine.search("decisao", sort="oldest")

        self.assertEqual(response.results[0].date_str, "20240115")

    def test_search_exact_phrase_requires_adjacent_terms(self):
        engine = PDFSearchEngine()

        all_terms = engine.search("lima pereira")
        exact_phrase = engine.search("lima pereira", match_mode=MATCH_EXACT_PHRASE)

        self.assertEqual(all_terms.total, 4)
        self.assertEqual(exact_phrase.total, 3)
        self.assertEqual(exact_phrase.results[0].date_str, "20250409")

    def test_search_near_context_requires_terms_within_distance(self):
        engine = PDFSearchEngine()

        near = engine.search(
            "melquizedeque lima pereira",
            match_mode=MATCH_NEAR_CONTEXT,
            related_query="elogiar",
            context_distance=20,
        )
        broader = engine.search(
            "melquizedeque lima pereira",
            match_mode=MATCH_NEAR_CONTEXT,
            related_query="elogiar",
            context_distance=220,
        )

        self.assertEqual(near.total, 1)
        self.assertEqual(near.results[0].date_str, "20260111")
        self.assertEqual(broader.total, 2)

    def test_empty_search_does_not_query_fts(self):
        engine = PDFSearchEngine()
        response = engine.search("   ")

        self.assertEqual(response.total, 0)
        self.assertEqual(response.results, [])


if __name__ == "__main__":
    unittest.main()
