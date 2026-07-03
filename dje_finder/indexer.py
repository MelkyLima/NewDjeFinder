import fitz  # PyMuPDF
import queue as q
import sqlite3
import threading
from datetime import datetime
from dje_finder.config import Config, logger
from dje_finder.persistence import get_db_connection


# Quantos PDFs acumular antes de fazer um COMMIT (batch)
COMMIT_BATCH_SIZE = 20


def extract_text_mp(pdf_path, date_str):
    """Função estática de extração de texto para rodar em subprocessos (Multiprocessing).
    Precisa estar no nível de módulo para ser serializável (picklable) pelo Windows.
    """
    import fitz
    try:
        doc = fitz.open(pdf_path)
        parts = []
        for page in doc:
            text = (page.get_text() or "").replace("\x00", "")
            if text.strip():
                parts.append(text)
        doc.close()
        full_text = "\n".join(parts)
        return date_str, full_text, None
    except Exception as e:
        return date_str, None, str(e)


class PDFIndexer:
    def __init__(self):
        self._write_lock = threading.Lock()
        self._stop_event = threading.Event()

    def stop(self):
        """Sinaliza para interromper o index_all_pending."""
        self._stop_event.set()

    def reset_stop(self):
        """Limpa o sinal de parada para permitir nova execução."""
        self._stop_event.clear()

    def get_pdf_path(self, date_str):
        year = date_str[:4]
        return Config.BASE_DIR / year / f"dpj-{date_str}.pdf"

    def clear_index(self, date_str, conn):
        """Limpa entradas de indexação anteriores para evitar duplicatas.
        Recebe a conexão externa — o caller é responsável pelo commit.
        """
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pdf_pages_fts WHERE date_str = ?", (date_str,))
        cursor.execute("DELETE FROM indexed_pdfs WHERE date_str = ?", (date_str,))

    # ------------------------------------------------------------------
    # _extract_text: extração pura, sem acesso ao banco
    # ------------------------------------------------------------------
    def _extract_text(self, date_str):
        """Extrai e concatena todo o texto do PDF em uma única string.
        Projetado para rodar em múltiplas threads sem qualquer conflito.
        Retorna: (date_str, full_text, error_msg)
        """
        if self._stop_event.is_set():
            return date_str, None, "Interrompido pelo usuário"

        pdf_path = self.get_pdf_path(date_str)
        if not pdf_path.is_file():
            return date_str, None, "Arquivo não encontrado"

        try:
            doc = fitz.open(pdf_path)
            parts = []
            for page in doc:
                text = (page.get_text() or "").replace("\x00", "")
                if text.strip():
                    parts.append(text)
            doc.close()
            full_text = "\n".join(parts)
            return date_str, full_text, None
        except Exception as e:
            return date_str, None, str(e)

    # ------------------------------------------------------------------
    # index_pdf: usado no fluxo de download (chamado individualmente)
    # ------------------------------------------------------------------
    def index_pdf(self, date_str):
        """Indexa um único PDF. Chamado pelo fluxo de download.
        Usa _write_lock para serializar escritas quando há múltiplos
        downloads simultâneos, evitando conflitos no SQLite.
        """
        # 1. Extrai texto fora do lock (I/O puro — paralelizável)
        _, full_text, extraction_error = self._extract_text(date_str)

        # 2. Escreve no banco com lock
        with self._write_lock:
            conn = get_db_connection()
            try:
                # Otimização: Só faz o lento DELETE no FTS5 se o PDF já foi indexado antes
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM indexed_pdfs WHERE date_str = ?", (date_str,))
                exists = cursor.fetchone() is not None
                if exists:
                    self.clear_index(date_str, conn)
                
                if extraction_error:
                    cursor.execute(
                        "INSERT INTO indexed_pdfs (date_str, indexed_at, status, error_message) VALUES (?, ?, ?, ?)",
                        (date_str, datetime.now().isoformat(), "FAILED", extraction_error)
                    )
                elif not full_text or not full_text.strip():
                    cursor.execute(
                        "INSERT INTO indexed_pdfs (date_str, indexed_at, status, error_message) VALUES (?, ?, ?, ?)",
                        (date_str, datetime.now().isoformat(), "SUCCESS", "PDF sem conteúdo")
                    )
                else:
                    cursor.execute(
                        "INSERT INTO pdf_pages_fts (date_str, content) VALUES (?, ?)",
                        (date_str, full_text)
                    )
                    cursor.execute(
                        "INSERT INTO indexed_pdfs (date_str, indexed_at, status, error_message) VALUES (?, ?, ?, ?)",
                        (date_str, datetime.now().isoformat(), "SUCCESS", None)
                    )

                conn.commit()
                if not extraction_error:
                    logger.info(f"PDF {date_str} indexado com sucesso.")
                return extraction_error is None
            except sqlite3.Error as se:
                logger.error(f"Erro de banco ao indexar {date_str}: {se}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                return False
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # index_all_pending: padrão produtor-consumidor
    # ------------------------------------------------------------------
    def index_all_pending(self, progress_callback=None, max_workers=None):
        """Indexa todos os PDFs pendentes usando padrão produtor-consumidor:

        Produtores (N processos): extraem texto dos PDFs em paralelo via ProcessPoolExecutor
                                  (ignora o GIL do Python e usa múltiplos núcleos reais de CPU).
        Consumidor (1 thread): faz todos os INSERTs no SQLite, sem concorrência,
                               em batches de COMMIT_BATCH_SIZE PDFs por transação.

        Schema v2: 1 linha por PDF (texto concatenado de todas as páginas).
        Isso elimina ~99% dos INSERTs FTS5 em comparação com 1 linha por página.
        """
        import os
        from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED

        self.reset_stop()

        pending_dates = self.get_pending_dates()
        total = len(pending_dates)
        if total == 0:
            if progress_callback:
                progress_callback(0, 0, "")
            return 0

        # Obtém conjunto de datas já registradas para evitar o lento DELETE do FTS5
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT date_str FROM indexed_pdfs")
            already_indexed = {r[0] for r in cursor.fetchall()}
        except sqlite3.Error:
            already_indexed = set()
        finally:
            conn.close()

        # Para processos de CPU, cpu // 2 equilibra bem a performance sem travar a máquina do usuário
        if max_workers is None:
            cpu = os.cpu_count() or 4
            max_workers = max(2, cpu // 2)

        # Fila com backpressure no processo principal
        write_queue = q.Queue(maxsize=max_workers * 2)

        indexed_count = 0
        completed_count = 0
        writer_crashed = threading.Event()
        count_lock = threading.Lock()

        # ------------------------------------------------------------------
        # Thread consumidora: único escritor do banco
        # ------------------------------------------------------------------
        def db_writer():
            nonlocal indexed_count, completed_count
            conn = get_db_connection()
            try:
                # Pragmas para maximizar velocidade de escrita em bulk
                conn.execute("PRAGMA synchronous = NORMAL")
                conn.execute("PRAGMA cache_size = -65536")   # 64 MB cache
                conn.execute("PRAGMA temp_store = MEMORY")

                batch_pending = 0

                while True:
                    # Timeout evita deadlock se producer crashar
                    try:
                        item = write_queue.get(timeout=60.0)
                    except q.Empty:
                        logger.warning("db_writer: timeout aguardando item. Encerrando.")
                        break

                    if item is None:  # sentinel — encerrar
                        write_queue.task_done()
                        if batch_pending > 0:
                            try:
                                conn.commit()
                            except Exception:
                                pass
                        break

                    date_str, full_text, error = item
                    current = 0  # sempre inicializado (evita NameError)
                    try:
                        # Otimização crucial: Só limpa se a data já existia no banco,
                        # evitando varredura FTS5 DELETE desnecessária
                        if date_str in already_indexed:
                            self.clear_index(date_str, conn)
                        cursor = conn.cursor()

                        if error:
                            cursor.execute(
                                "INSERT INTO indexed_pdfs (date_str, indexed_at, status, error_message) VALUES (?, ?, ?, ?)",
                                (date_str, datetime.now().isoformat(), "FAILED", error)
                            )
                            logger.warning(f"PDF {date_str} marcado como FAILED: {error}")
                        elif not full_text or not full_text.strip():
                            cursor.execute(
                                "INSERT INTO indexed_pdfs (date_str, indexed_at, status, error_message) VALUES (?, ?, ?, ?)",
                                (date_str, datetime.now().isoformat(), "SUCCESS", "PDF sem conteúdo")
                            )
                        else:
                            cursor.execute(
                                "INSERT INTO pdf_pages_fts (date_str, content) VALUES (?, ?)",
                                (date_str, full_text)
                            )
                            cursor.execute(
                                "INSERT INTO indexed_pdfs (date_str, indexed_at, status, error_message) VALUES (?, ?, ?, ?)",
                                (date_str, datetime.now().isoformat(), "SUCCESS", None)
                            )
                            logger.info(f"PDF {date_str} indexado com sucesso.")

                        batch_pending += 1
                        if batch_pending >= COMMIT_BATCH_SIZE:
                            conn.commit()
                            batch_pending = 0

                        with count_lock:
                            if not error:
                                indexed_count += 1
                            completed_count += 1
                            current = completed_count

                    except Exception as e:
                        logger.error(f"Erro ao gravar {date_str} no banco: {e}")
                        try:
                            conn.rollback()
                            batch_pending = 0
                        except Exception:
                            pass
                        with count_lock:
                            completed_count += 1
                            current = completed_count
                    finally:
                        write_queue.task_done()

                    if progress_callback:
                        try:
                            progress_callback(current, total, date_str)
                        except Exception:
                            pass

            except Exception as e:
                logger.error(f"Erro crítico na thread escritora: {e}")
                writer_crashed.set()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        # Inicia thread escritora
        writer_thread = threading.Thread(target=db_writer, daemon=True, name="IndexerWriter")
        writer_thread.start()

        # ------------------------------------------------------------------
        # Produtores: extração de texto em paralelo via ProcessPoolExecutor
        # ------------------------------------------------------------------
        active_futures = set()
        pending_list = list(pending_dates)

        try:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                while pending_list or active_futures:
                    if self._stop_event.is_set() or writer_crashed.is_set():
                        for f in active_futures:
                            f.cancel()
                        break

                    # Submete novas tarefas até o limite regulador (max_workers * 2)
                    while pending_list and len(active_futures) < max_workers * 2:
                        d = pending_list.pop(0)
                        pdf_path = self.get_pdf_path(d)
                        future = executor.submit(extract_text_mp, pdf_path, d)
                        active_futures.add(future)

                    # Aguarda pelo menos uma tarefa concluir (timeout baixo para permitir cancelamento)
                    done, active_futures = wait(active_futures, return_when=FIRST_COMPLETED, timeout=0.1)

                    # Coleta resultados das concluídas
                    for future in done:
                        try:
                            result = future.result()

                            # Tenta enfileirar com timeout/backpressure
                            placed = False
                            for _ in range(3):
                                if writer_crashed.is_set() or self._stop_event.is_set():
                                    break
                                try:
                                    write_queue.put(result, timeout=30.0)
                                    placed = True
                                    break
                                except q.Full:
                                    logger.warning("Fila de escrita cheia, aguardando escritor...")

                            if not placed and not writer_crashed.is_set() and not self._stop_event.is_set():
                                logger.error("Não foi possível enfileirar resultado de extração MP.")
                                writer_crashed.set()
                        except Exception as e:
                            logger.error(f"Erro ao recuperar resultado do ProcessPoolExecutor: {e}")

        finally:
            # Sentinel: sinaliza ao db_writer que não há mais itens
            try:
                write_queue.put(None, timeout=10.0)
            except q.Full:
                logger.warning("Fila cheia ao enviar sentinel. Forçando encerramento.")
                writer_crashed.set()

            writer_thread.join(timeout=120.0)
            if writer_thread.is_alive():
                logger.warning("Thread escritora não encerrou no tempo esperado.")

        return indexed_count

    def get_pending_dates(self):
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.date_str
                FROM pdfs p
                LEFT JOIN indexed_pdfs i ON p.date_str = i.date_str
                WHERE i.status IS NULL OR i.status != 'SUCCESS'
                ORDER BY p.date_str ASC
            """)
            rows = cursor.fetchall()
            return [r[0] for r in rows]
        except sqlite3.Error as e:
            logger.error(f"Erro ao buscar PDFs pendentes de indexação: {e}")
            return []
        finally:
            conn.close()

    def get_stats(self):
        conn = get_db_connection()
        stats = {
            "total_baixados": 0,
            "total_indexados": 0,
            "total_falhas": 0,
            "total_paginas": 0
        }
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM pdfs")
            stats["total_baixados"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM indexed_pdfs WHERE status = 'SUCCESS'")
            stats["total_indexados"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM indexed_pdfs WHERE status = 'FAILED'")
            stats["total_falhas"] = cursor.fetchone()[0]

            # total_paginas agora conta PDFs indexados (1 linha = 1 PDF no schema v2)
            cursor.execute("SELECT COUNT(*) FROM pdf_pages_fts")
            stats["total_paginas"] = cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"Erro ao obter estatísticas de indexação: {e}")
        finally:
            conn.close()
        return stats
