import json
import re
import sqlite3
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dje_finder.config import Config, logger

def get_db_connection():
    Config.DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(Config.DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pdfs (
            date_str TEXT PRIMARY KEY
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS datas_sem_pdf (
            date_str TEXT PRIMARY KEY
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            val TEXT
        )
    """)
    conn.commit()
    conn.close()
    
    # Executa a migração automática de JSON antigo se existir
    migrate_json_to_sqlite()

def migrate_json_to_sqlite():
    # 1. Migrar índice
    if Config.INDEX_FILE.exists():
        logger.info("Localizado 'indice.json' antigo. Iniciando migração para o SQLite...")
        try:
            with open(Config.INDEX_FILE, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            if "ultima_data_indexada" in index_data:
                cursor.execute(
                    "INSERT OR REPLACE INTO state (key, val) VALUES (?, ?)",
                    ("ultima_data_indexada", str(index_data["ultima_data_indexada"]))
                )
                
            if isinstance(index_data.get("pdfs"), list):
                cursor.executemany(
                    "INSERT OR IGNORE INTO pdfs (date_str) VALUES (?)",
                    [(d,) for d in index_data["pdfs"]]
                )
                
            if isinstance(index_data.get("datas_sem_pdf"), list):
                cursor.executemany(
                    "INSERT OR IGNORE INTO datas_sem_pdf (date_str) VALUES (?)",
                    [(d,) for d in index_data["datas_sem_pdf"]]
                )
                
            conn.commit()
            conn.close()
            
            backup_path = Config.INDEX_FILE.with_suffix(".json.bak")
            Config.INDEX_FILE.replace(backup_path)
            logger.info("Migração de 'indice.json' concluída com sucesso!")
        except Exception as e:
            logger.exception(f"Erro ao migrar 'indice.json': {e}")
            
    # 2. Migrar estado
    if Config.STATE_FILE.exists():
        logger.info("Localizado 'estado.json' antigo. Iniciando migração para o SQLite...")
        try:
            with open(Config.STATE_FILE, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
                
            conn = get_db_connection()
            cursor = conn.cursor()
            for k, v in state_data.items():
                if isinstance(v, (list, dict)):
                    val_str = json.dumps(v)
                else:
                    val_str = str(v)
                cursor.execute(
                    "INSERT OR REPLACE INTO state (key, val) VALUES (?, ?)",
                    (k, val_str)
                )
            conn.commit()
            conn.close()
            
            backup_path = Config.STATE_FILE.with_suffix(".json.bak")
            Config.STATE_FILE.replace(backup_path)
            logger.info("Migração de 'estado.json' concluída com sucesso!")
        except Exception as e:
            logger.exception(f"Erro ao migrar 'estado.json': {e}")

def is_valid_pdf_file(path):
    try:
        if not path.is_file() or path.stat().st_size <= 4:
            return False
        with open(path, "rb") as file:
            return file.read(4) == b"%PDF"
    except OSError:
        return False

class IndexManager:
    def __init__(self):
        self.lock = threading.Lock()
        init_db()
        self.data = {
            "ultima_data_indexada": Config.START_DATE,
            "pdfs": [],
            "datas_sem_pdf": []
        }
        self.load()

    def load(self):
        with self.lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute("SELECT val FROM state WHERE key = 'ultima_data_indexada'")
                row = cursor.fetchone()
                if row:
                    self.data["ultima_data_indexada"] = row[0]
                else:
                    self.data["ultima_data_indexada"] = Config.START_DATE
                    
                cursor.execute("SELECT date_str FROM pdfs ORDER BY date_str ASC")
                self.data["pdfs"] = [r[0] for r in cursor.fetchall()]
                
                cursor.execute("SELECT date_str FROM datas_sem_pdf ORDER BY date_str ASC")
                self.data["datas_sem_pdf"] = [r[0] for r in cursor.fetchall()]
                
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"Erro ao carregar índice do SQLite: {e}")

    def save(self):
        with self.lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute(
                    "INSERT OR REPLACE INTO state (key, val) VALUES ('ultima_data_indexada', ?)",
                    (self.data["ultima_data_indexada"],)
                )
                
                cursor.execute("DELETE FROM pdfs")
                cursor.executemany(
                    "INSERT INTO pdfs (date_str) VALUES (?)",
                    [(d,) for d in self.data["pdfs"]]
                )
                
                cursor.execute("DELETE FROM datas_sem_pdf")
                cursor.executemany(
                    "INSERT INTO datas_sem_pdf (date_str) VALUES (?)",
                    [(d,) for d in self.data["datas_sem_pdf"]]
                )
                
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"Erro ao salvar índice no SQLite: {e}")

    def extract_pdf_date(self, pdf_path):
        match = re.match(r"^dpj-(\d{8})\.pdf$", pdf_path.name, re.IGNORECASE)
        if not match:
            return None

        date_str = match.group(1)
        if is_valid_pdf_file(pdf_path):
            return date_str
        return None

    def scan_existing_pdfs(self, progress_callback=None):
        discovered_dates = set()

        if not Config.BASE_DIR.exists():
            if progress_callback:
                progress_callback("scan", 0, 0, 0)
            return discovered_dates

        pdf_paths = list(Config.BASE_DIR.rglob("dpj-*.pdf"))
        total_paths = len(pdf_paths)
        if progress_callback:
            progress_callback("scan", 0, total_paths, 0)

        if total_paths:
            with ThreadPoolExecutor(max_workers=Config.LOCAL_SCAN_WORKERS) as executor:
                futures = [executor.submit(self.extract_pdf_date, pdf_path) for pdf_path in pdf_paths]
                for current_path, future in enumerate(as_completed(futures), start=1):
                    date_str = future.result()
                    if date_str:
                        discovered_dates.add(date_str)

                    if progress_callback and (current_path == total_paths or current_path % 100 == 0):
                        progress_callback("scan", current_path, total_paths, len(discovered_dates))

        if discovered_dates:
            with self.lock:
                current_dates = set(self.data.get("pdfs", []))
                current_dates.update(discovered_dates)
                self.data["pdfs"] = sorted(current_dates)
                last_discovered = max(discovered_dates)
                if last_discovered > self.data.get("ultima_data_indexada", Config.START_DATE):
                    self.data["ultima_data_indexada"] = last_discovered
            self.save()

        return discovered_dates

    def find_missing_gap_dates(self, dates):
        from datetime import datetime, timedelta
        missing_dates = set()
        sorted_dates = sorted(dates)
        if len(sorted_dates) < 2:
            return missing_dates

        previous_date = datetime.strptime(sorted_dates[0], "%Y%m%d")
        for date_str in sorted_dates[1:]:
            current_date = datetime.strptime(date_str, "%Y%m%d")
            gap_days = (current_date - previous_date).days
            if gap_days > Config.BACKUP_GAP_DAYS:
                missing_date = previous_date + timedelta(days=1)
                while missing_date < current_date:
                    missing_dates.add(missing_date.strftime("%Y%m%d"))
                    missing_date += timedelta(days=1)
            previous_date = current_date

        return missing_dates

    def add_pdf(self, date_str):
        with self.lock:
            if date_str not in self.data["pdfs"]:
                self.data["pdfs"].append(date_str)
                self.data["pdfs"].sort()
            if date_str in self.data.get("datas_sem_pdf", []):
                self.data["datas_sem_pdf"].remove(date_str)
                
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO pdfs (date_str) VALUES (?)", (date_str,))
                cursor.execute("DELETE FROM datas_sem_pdf WHERE date_str = ?", (date_str,))
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"Erro ao adicionar PDF no SQLite: {e}")

    def add_absent_date(self, date_str):
        with self.lock:
            if date_str not in self.data["datas_sem_pdf"]:
                self.data["datas_sem_pdf"].append(date_str)
                self.data["datas_sem_pdf"].sort()
            if date_str in self.data.get("pdfs", []):
                self.data["pdfs"].remove(date_str)
                
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO datas_sem_pdf (date_str) VALUES (?)", (date_str,))
                cursor.execute("DELETE FROM pdfs WHERE date_str = ?", (date_str,))
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"Erro ao adicionar data ausente no SQLite: {e}")

    def update_last_date(self, date_str):
        with self.lock:
            if date_str > self.data.get("ultima_data_indexada", ""):
                self.data["ultima_data_indexada"] = date_str
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT OR REPLACE INTO state (key, val) VALUES ('ultima_data_indexada', ?)",
                        (date_str,)
                    )
                    conn.commit()
                    conn.close()
                except sqlite3.Error as e:
                    logger.error(f"Erro ao atualizar última data no SQLite: {e}")

class StateManager:
    def __init__(self):
        self.lock = threading.Lock()
        init_db()
        self.data = {
            "fila_restante": [],
            "em_andamento": [],
            "falhas": [],
            "pdf_atual": "",
            "baixados": 0,
            "localizados": 0,
            "atualizaveis": 0
        }

    def has_valid_state(self):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT val FROM state WHERE key IN ('fila_restante', 'em_andamento', 'falhas')")
            rows = cursor.fetchall()
            conn.close()
            
            for row in rows:
                if row[0]:
                    try:
                        lst = json.loads(row[0])
                        if isinstance(lst, list) and len(lst) > 0:
                            return True
                    except json.JSONDecodeError:
                        continue
        except sqlite3.Error:
            pass
        return False

    def load(self):
        with self.lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT key, val FROM state")
                rows = cursor.fetchall()
                conn.close()
                
                for row in rows:
                    key, val = row[0], row[1]
                    if key in ("fila_restante", "em_andamento", "falhas"):
                        try:
                            self.data[key] = json.loads(val)
                        except json.JSONDecodeError:
                            self.data[key] = []
                    elif key == "pdf_atual":
                        self.data[key] = val
                    elif key in ("baixados", "localizados", "atualizaveis"):
                        try:
                            self.data[key] = int(val)
                        except ValueError:
                            self.data[key] = 0
            except sqlite3.Error as e:
                logger.error(f"Erro ao carregar estado do SQLite: {e}")

    def save(self):
        with self.lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                for k, v in self.data.items():
                    if isinstance(v, (list, dict)):
                        val_str = json.dumps(v)
                    else:
                        val_str = str(v)
                    cursor.execute("INSERT OR REPLACE INTO state (key, val) VALUES (?, ?)", (k, val_str))
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"Erro ao salvar estado no SQLite: {e}")

    def clear(self):
        with self.lock:
            self.data = {
                "fila_restante": [],
                "em_andamento": [],
                "falhas": [],
                "pdf_atual": "",
                "baixados": 0,
                "localizados": 0,
                "atualizaveis": 0
            }
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM state WHERE key IN ('fila_restante', 'em_andamento', 'falhas', 'pdf_atual', 'baixados', 'localizados', 'atualizaveis')"
                )
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"Erro ao limpar estado no SQLite: {e}")
