import threading
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from dje_finder.config import Config, TokenBucket, logger
from dje_finder.network import PDFDiscovery, DownloadManager

class WorkerController:
    def __init__(self, index_mgr, state_mgr, gui_queue):
        self.index_mgr = index_mgr
        self.state_mgr = state_mgr
        self.gui_queue = gui_queue
        self.executor = None
        self.running = False
        self.paused = False
        self.active_futures = set()
        self.active_dates = set()
        self.lock = threading.RLock()
        self.max_workers = 1
        self.fila = []
        self.total_bytes = 0
        self.processed_dates = 0
        self.bytes_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        self.limiter = None
        self.consecutive_errors = 0

    def update_limiter(self, speed_config):
        if "Lento" in speed_config:
            self.limiter = TokenBucket(1)
            self.max_workers = 2
        elif "Rápido" in speed_config:
            self.limiter = TokenBucket(5)
            self.max_workers = 8
        else: # Turbo
            self.limiter = TokenBucket(0) # Infinite
            self.max_workers = 16

    def add_bytes(self, n):
        with self.bytes_lock:
            self.total_bytes += n

    def mark_processed_date(self):
        with self.stats_lock:
            self.processed_dates += 1

    def build_queue(self, progress_callback=None):
        discovered_dates = self.index_mgr.scan_existing_pdfs(progress_callback)
        missing_gap_dates = self.index_mgr.find_missing_gap_dates(discovered_dates)
        if progress_callback:
            progress_callback("gaps", len(missing_gap_dates), len(missing_gap_dates), len(discovered_dates))
        fila_salva = set(self.state_mgr.data.get("fila_restante", []))
        fila_salva.update(self.state_mgr.data.get("em_andamento", []))
        fila_salva.update(self.state_mgr.data.get("falhas", []))
        datas_sem_pdf = set(self.index_mgr.data.get("datas_sem_pdf", []))
        
        fila = set()
        baixados_dates = set(discovered_dates)
        
        for d in sorted(set(self.index_mgr.data["pdfs"])):
            if d in discovered_dates:
                baixados_dates.add(d)
            elif d not in datas_sem_pdf:
                fila.add(d)
                
        last_idx = self.index_mgr.data.get("ultima_data_indexada", Config.START_DATE)
        try:
            start_dt = datetime.strptime(last_idx, "%Y%m%d")
        except ValueError:
            start_dt = datetime.strptime(Config.START_DATE, "%Y%m%d")
            
        end_dt = datetime.today()
        current = start_dt + timedelta(days=1)
        
        while current <= end_dt:
            d = current.strftime("%Y%m%d")
            if d in discovered_dates:
                baixados_dates.add(d)
                self.index_mgr.add_pdf(d)
            elif d not in fila_salva and d not in datas_sem_pdf:
                fila.add(d)
            current += timedelta(days=1)

        for date_str in missing_gap_dates:
            if date_str not in discovered_dates and date_str not in datas_sem_pdf:
                fila.add(date_str)

        for d in fila_salva:
            if d in discovered_dates:
                baixados_dates.add(d)
                self.index_mgr.add_pdf(d)
            elif d not in datas_sem_pdf and (d > last_idx or d in missing_gap_dates):
                fila.add(d)

        self.fila = sorted(fila)
        
        baixados_count = len(baixados_dates)
        atualizaveis_count = len(self.fila)
        localizados_count = baixados_count + atualizaveis_count
        
        self.state_mgr.data["baixados"] = baixados_count
        self.state_mgr.data["atualizaveis"] = atualizaveis_count
        self.state_mgr.data["localizados"] = localizados_count
        self.state_mgr.data["fila_restante"] = self.fila
        self.state_mgr.data["em_andamento"] = []
        self.state_mgr.data["falhas"] = []
        self.state_mgr.save()
        self.index_mgr.save()

    def check_availability(self):
        import socket
        logger.info("Iniciando checagem de conectividade...")
        
        internet_ok = False
        for ip in ["8.8.8.8", "1.1.1.1"]:
            try:
                logger.info(f"Tentando conexão direta via socket com {ip}:53...")
                s = socket.create_connection((ip, 53), timeout=3)
                s.close()
                internet_ok = True
                logger.info(f"Conexão direta com {ip}:53 bem-sucedida!")
                break
            except OSError as e:
                logger.warning(f"Falha ao conectar com {ip}:53: {e}")
                continue
                
        if not internet_ok:
            logger.error("Nenhuma conexão de rede detectada (8.8.8.8 e 1.1.1.1 inacessíveis).")
            return "INTERNET_OFF"
            
        portal_url = "https://diario.tjrr.jus.br"
        try:
            logger.info(f"Tentando requisição HTTP GET para o portal: {portal_url}...")
            response = requests.get(
                portal_url,
                timeout=5,
                headers={"User-Agent": Config.USER_AGENT}
            )
            logger.info(f"Resposta do portal recebida. HTTP Status: {response.status_code}")
            if response.status_code >= 500:
                logger.error(f"Portal retornou erro de servidor: {response.status_code}")
                return "PORTAL_OFF"
            return "OK"
        except requests.RequestException as e:
            logger.exception(f"Erro ao acessar o portal {portal_url}:")
            return f"PORTAL_OFF (Erro: {e})"

    def check_availability_with_timeout(self, timeout=8):
        result = [None]
        def worker():
            try:
                result[0] = self.check_availability()
            except Exception as e:
                logger.exception("Erro interno na checagem de disponibilidade:")
                result[0] = f"ERROR: {e}"
                
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout)
        
        if t.is_alive():
            logger.error(f"A checagem de conectividade excedeu o limite de {timeout} segundos e foi abortada.")
            return "PORTAL_OFF (Timeout)"
            
        return result[0]

    def _check_and_run_sync(self, speed_config):
        try:
            self.gui_queue.put({"type": "checking_connection"})
            status = self.check_availability_with_timeout(8)
            logger.info(f"Resultado da checagem de disponibilidade: {status}")
            
            if status == "INTERNET_OFF":
                self.running = False
                self.gui_queue.put({"type": "connection_error", "error_type": "internet"})
                return
            elif isinstance(status, str) and status.startswith("PORTAL_OFF"):
                self.running = False
                self.gui_queue.put({"type": "connection_error", "error_type": "portal", "error_detail": status})
                return
            elif isinstance(status, str) and status.startswith("ERROR"):
                self.running = False
                self.gui_queue.put({"type": "connection_error", "error_type": "portal", "error_detail": status})
                return
                
            with self.lock:
                if not self.running or self.paused:
                    return
                self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
                with self.bytes_lock:
                    self.consecutive_errors = 0
                for _ in range(self.max_workers):
                    self.submit_next()
            self.gui_queue.put({"type": "sync_started"})
            self.send_gui_update(None, None)
        except Exception as error:
            logger.exception("Erro inesperado em _check_and_run_sync:")
            self.running = False
            self.gui_queue.put({
                "type": "connection_error",
                "error_type": "portal",
                "error_detail": str(error)
            })

    def _check_and_resume_sync(self, speed_config):
        try:
            self.gui_queue.put({"type": "checking_connection"})
            status = self.check_availability_with_timeout(8)
            logger.info(f"Resultado da checagem de disponibilidade: {status}")
            
            if status == "INTERNET_OFF":
                self.paused = True
                self.gui_queue.put({"type": "connection_error", "error_type": "internet"})
                return
            elif isinstance(status, str) and status.startswith("PORTAL_OFF"):
                self.paused = True
                self.gui_queue.put({"type": "connection_error", "error_type": "portal", "error_detail": status})
                return
            elif isinstance(status, str) and status.startswith("ERROR"):
                self.paused = True
                self.gui_queue.put({"type": "connection_error", "error_type": "portal", "error_detail": status})
                return
                
            with self.lock:
                if self.paused or not self.running:
                    return
                current_active = len(self.active_futures)
                if self.executor and current_active == 0:
                    self.executor.shutdown(wait=False, cancel_futures=True)
                    self.executor = None
                if not self.executor:
                    self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
                with self.bytes_lock:
                    self.consecutive_errors = 0
                diff = self.max_workers - current_active
                if diff > 0:
                    for _ in range(diff):
                        self.submit_next()
            self.gui_queue.put({"type": "sync_started"})
            self.send_gui_update(None, None)
        except Exception as error:
            logger.exception("Erro inesperado em _check_and_resume_sync:")
            self.paused = True
            self.gui_queue.put({
                "type": "connection_error",
                "error_type": "portal",
                "error_detail": str(error)
            })

    def start(self, speed_config):
        if self.running:
            return
        self.update_limiter(speed_config)
        self.running = True
        self.paused = False
        threading.Thread(target=self._check_and_run_sync, args=(speed_config,), daemon=True).start()

    def pause(self):
        self.paused = True
        self.send_gui_update(None, None)

    def resume(self, speed_config):
        self.update_limiter(speed_config)
        self.paused = False
        self.running = True
        threading.Thread(target=self._check_and_resume_sync, args=(speed_config,), daemon=True).start()

    def submit_next(self):
        with self.lock:
            if self.paused or not self.running:
                return
            if not self.fila:
                if len(self.active_futures) == 0:
                    message_type = "done_with_errors" if self.state_mgr.data.get("falhas") else "done"
                    self.gui_queue.put({"type": message_type})
                return
            
            date_str = self.fila.pop(0)
            self.state_mgr.data["fila_restante"] = list(self.fila)
            self.active_dates.add(date_str)
            self.state_mgr.data["em_andamento"] = sorted(self.active_dates)
            self.state_mgr.save()
            future = self.executor.submit(self.process_date, date_str)
            self.active_futures.add(future)
        future.add_done_callback(lambda f, d=date_str: self.future_done(f, d))
        self.send_gui_update(date_str, None)

    def process_date(self, date_str):
        if DownloadManager.is_downloaded(date_str):
            self.index_mgr.add_pdf(date_str)
            return "EXISTE", date_str, None
        
        res = PDFDiscovery.check_and_stream(date_str)
        if isinstance(res, Exception):
            return "ERRO", date_str, res
        elif res is None:
            return "NAO_ENCONTRADO", date_str, None
        else:
            save_res = DownloadManager.save_pdf(res, date_str, self.add_bytes, self.limiter)
            if isinstance(save_res, Exception):
                return "ERRO", date_str, save_res
            else:
                self.index_mgr.add_pdf(date_str)
                return "BAIXADO", date_str, None

    def future_done(self, future, date_str):
        try:
            status, d_str, err = future.result()
        except Exception as e:
            status, d_str, err = "ERRO", date_str, e

        with self.lock:
            self.active_futures.discard(future)
            self.active_dates.discard(d_str)
            self.mark_processed_date()
            self.index_mgr.update_last_date(d_str)
            self.state_mgr.data["pdf_atual"] = d_str
            
            if status in ("EXISTE", "BAIXADO"):
                self.state_mgr.data["baixados"] += 1
                with self.bytes_lock:
                    self.consecutive_errors = 0
            elif status == "NAO_ENCONTRADO":
                self.index_mgr.add_absent_date(d_str)
                with self.bytes_lock:
                    self.consecutive_errors = 0
            elif status == "ERRO":
                failures = set(self.state_mgr.data.get("falhas", []))
                failures.add(d_str)
                self.state_mgr.data["falhas"] = sorted(failures)
                with self.bytes_lock:
                    self.consecutive_errors += 1
                    errors_count = self.consecutive_errors
                if errors_count >= 5:
                    self.paused = True
                    self.gui_queue.put({"type": "portal_unstable", "error": str(err)})
                
            self.state_mgr.data["atualizaveis"] = len(self.fila) + len(self.active_futures)
            self.state_mgr.data["localizados"] = self.state_mgr.data["baixados"] + self.state_mgr.data["atualizaveis"]
            self.state_mgr.data["fila_restante"] = list(self.fila)
            self.state_mgr.data["em_andamento"] = sorted(self.active_dates)
            
            self.state_mgr.save()
            self.index_mgr.save()

        self.send_gui_update(d_str, err)
        self.submit_next()

    def finish(self, clear_state=True):
        self.running = False
        self.paused = False
        if self.executor:
            self.executor.shutdown(wait=False)
            self.executor = None
        if clear_state:
            self.state_mgr.clear()
        else:
            self.state_mgr.save()

    def stop(self):
        self.running = False
        self.paused = True
        self.state_mgr.data["fila_restante"] = sorted(set(self.fila))
        self.state_mgr.data["em_andamento"] = sorted(self.active_dates)
        self.state_mgr.save()
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)

    def send_gui_update(self, date_str, err):
        self.gui_queue.put({
            "type": "update",
            "date": date_str or self.state_mgr.data.get("pdf_atual", ""),
            "error": str(err) if err else None,
            "baixados": self.state_mgr.data.get("baixados", 0),
            "localizados": self.state_mgr.data.get("localizados", 0),
            "atualizaveis": self.state_mgr.data.get("atualizaveis", 0),
            "em_progresso": len(self.active_futures),
            "restantes": len(self.fila),
            "total_bytes": self.total_bytes,
            "processed_dates": self.processed_dates
        })
