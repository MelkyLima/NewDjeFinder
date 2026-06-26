import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from dje_finder.config import APP_NAME, logger
from dje_finder.persistence import IndexManager, StateManager
from dje_finder.worker import WorkerController

class TJRRSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("520x550")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.gui_queue = queue.Queue()
        self.index_mgr = IndexManager()
        self.state_mgr = StateManager()
        self.worker = WorkerController(self.index_mgr, self.state_mgr, self.gui_queue)
        self.initializing = True
        
        self.last_bytes = 0
        self.last_processed_dates = 0
        self.last_time = time.time()
        
        self.setup_ui()
        self.check_initial_state()
        self.root.after(100, self.prepare_initial_queue)
        self.process_queue()
        self.update_speed_label()

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        self.btn_action = ttk.Button(main_frame, text="ATUALIZAR Base de PDFs", command=self.toggle_action)
        self.btn_action.pack(side=tk.BOTTOM, fill=tk.X, ipady=8, pady=(10, 0))
        
        self.lbl_erro = ttk.Label(main_frame, text="", foreground="red", wraplength=480)
        self.lbl_erro.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.lbl_pdf_atual = ttk.Label(main_frame, text="PDF atual: Aguardando...", font=("Segoe UI", 10, "bold"))
        self.lbl_pdf_atual.pack(anchor=tk.W, pady=(0, 10))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))
        
        self.lbl_pct = ttk.Label(main_frame, text="0.00%")
        self.lbl_pct.pack(anchor=tk.E, pady=(0, 15))
        
        info_frame = ttk.LabelFrame(main_frame, text="Estatísticas", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.lbl_localizados = ttk.Label(info_frame, text="PDFs Totais localizados: 0")
        self.lbl_localizados.pack(anchor=tk.W, pady=2)
        
        self.lbl_atualizaveis = ttk.Label(info_frame, text="Datas pendentes de verificação: 0")
        self.lbl_atualizaveis.pack(anchor=tk.W, pady=2)
        
        self.lbl_baixados = ttk.Label(info_frame, text="PDFs Totais baixados: 0")
        self.lbl_baixados.pack(anchor=tk.W, pady=2)
        
        self.lbl_progresso = ttk.Label(info_frame, text="PDFs em progresso: 0")
        self.lbl_progresso.pack(anchor=tk.W, pady=2)
        
        self.lbl_fila = ttk.Label(info_frame, text="PDFs na fila: 0")
        self.lbl_fila.pack(anchor=tk.W, pady=2)
        
        self.lbl_velocidade_real = ttk.Label(info_frame, text="Velocidade de download: 0 KB/s", font=("Segoe UI", 9, "italic"))
        self.lbl_velocidade_real.pack(anchor=tk.W, pady=2)
        
        speed_frame = ttk.Frame(main_frame)
        speed_frame.pack(fill=tk.X, pady=(0, 15))
        ttk.Label(speed_frame, text="Modo:").pack(side=tk.LEFT, padx=(0, 10))
        self.cb_speed = ttk.Combobox(speed_frame, values=["1 - Lento (1MB/s)", "2 - Rápido (5MB/s)", "3 - Turbo (Ilimitado)"], state="readonly")
        self.cb_speed.current(1)
        self.cb_speed.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def check_initial_state(self):
        if self.state_mgr.has_valid_state():
            if messagebox.askyesno(
                "Retomar Sessão",
                "Existe uma sincronização interrompida.\n\n"
                "Sim: continua a fila salva e tenta novamente as falhas.\n"
                "Não: descarta a fila salva e recalcula a base a partir dos PDFs existentes.",
            ):
                self.state_mgr.load()
            else:
                self.state_mgr.clear()
        
        self.btn_action.config(text="Preparando base local...", state="disabled")
        self.cb_speed.config(state="disabled")
        self.lbl_pdf_atual.config(text="Preparando base local. Aguarde...")

    def prepare_initial_queue(self):
        threading.Thread(target=self.build_initial_queue, daemon=True).start()

    def build_initial_queue(self):
        try:
            self.worker.build_queue(self.report_initial_progress)
            self.gui_queue.put({"type": "initial_ready"})
        except Exception as error:
            logger.exception("Não foi possível preparar a base local.")
            self.gui_queue.put({"type": "initial_error", "error": str(error)})

    def report_initial_progress(self, phase, current, total, found):
        self.gui_queue.put({
            "type": "initial_progress",
            "phase": phase,
            "current": current,
            "total": total,
            "found": found,
        })

    def update_initial_progress(self, msg):
        phase = msg["phase"]
        current = msg["current"]
        total = msg["total"]
        found = msg["found"]

        if phase == "scan":
            percent = (current / total) * 100.0 if total else 100.0
            self.progress_var.set(min(max(percent, 0.0), 100.0))
            self.lbl_pct.config(text=f"{percent:.2f}%")
            self.lbl_pdf_atual.config(
                text=f"Preparando base local: analisando {current}/{total} arquivos..."
            )
            self.lbl_localizados.config(text=f"PDFs encontrados localmente: {found}")
            self.lbl_atualizaveis.config(text=f"Arquivos analisados: {current}/{total}")
            self.lbl_baixados.config(text=f"PDFs válidos importados: {found}")
            self.lbl_progresso.config(text="Etapa atual: varredura local")
            self.lbl_fila.config(text="Datas na fila: calculando...")
        elif phase == "gaps":
            self.progress_var.set(100.0)
            self.lbl_pct.config(text="100.00%")
            self.lbl_pdf_atual.config(text="Preparando base local: procurando lacunas no acervo...")
            self.lbl_localizados.config(text=f"PDFs encontrados localmente: {found}")
            self.lbl_atualizaveis.config(text=f"Datas em lacunas grandes: {current}")
            self.lbl_baixados.config(text=f"PDFs válidos importados: {found}")
            self.lbl_progresso.config(text="Etapa atual: conferência de lacunas")
            self.lbl_fila.config(text="Datas na fila: calculando...")

    def finish_initial_queue(self):
        self.initializing = False
        self.btn_action.config(text="ATUALIZAR Base de PDFs", state="normal")
        self.cb_speed.config(state="readonly")
        self.lbl_pdf_atual.config(text="PDF atual: Aguardando...")
        self.update_labels(
            pdf="",
            baixados=self.state_mgr.data.get("baixados", 0),
            localizados=self.state_mgr.data.get("localizados", 0),
            atualizaveis=self.state_mgr.data.get("atualizaveis", 0),
            em_progresso=0,
            restantes=len(self.state_mgr.data.get("fila_restante", []))
        )
        
        if self.state_mgr.data.get("atualizaveis", 0) == 0 and self.state_mgr.data.get("localizados", 0) > 0:
            self.btn_action.config(text="Concluído", state="disabled")
            self.progress_var.set(100.0)
            self.lbl_pct.config(text="100.00%")

    def fail_initial_queue(self, error):
        self.initializing = False
        self.btn_action.config(text="ATUALIZAR Base de PDFs", state="normal")
        self.cb_speed.config(state="readonly")
        self.lbl_pdf_atual.config(text="Não foi possível preparar a base local.")
        self.lbl_erro.config(text=f"Erro ao preparar base local: {error}")

    def get_speed_config(self):
        return self.cb_speed.get()

    def toggle_action(self):
        if self.initializing:
            return
        txt = self.btn_action.cget("text")
        speed_cfg = self.get_speed_config()
        if txt == "ATUALIZAR Base de PDFs":
            self.btn_action.config(text="Pausar")
            self.cb_speed.config(state="disabled")
            self.worker.start(speed_cfg)
        elif txt == "Pausar":
            self.btn_action.config(text="Retomar")
            self.cb_speed.config(state="readonly")
            self.worker.pause()
        elif txt == "Retomar":
            self.btn_action.config(text="Pausar")
            self.cb_speed.config(state="disabled")
            self.worker.resume(speed_cfg)

    def update_labels(self, pdf, baixados, localizados, atualizaveis, em_progresso, restantes):
        if pdf:
            self.lbl_pdf_atual.config(text=f"PDF atual: dpj-{pdf}.pdf")
            
        self.lbl_localizados.config(text=f"PDFs Totais localizados: {localizados}")
        self.lbl_atualizaveis.config(text=f"Datas pendentes de verificação: {atualizaveis}")
        self.lbl_baixados.config(text=f"PDFs Totais baixados: {baixados}")
        self.lbl_progresso.config(text=f"PDFs em progresso: {em_progresso}")
        self.lbl_fila.config(text=f"PDFs na fila: {restantes}")
        
        if localizados > 0:
            pct = (baixados / localizados) * 100.0
        else:
            pct = 100.0 if atualizaveis == 0 else 0.0
            
        pct = min(max(pct, 0.0), 100.0)
        self.progress_var.set(pct)
        self.lbl_pct.config(text=f"{pct:.2f}%")

    def process_queue(self):
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                if msg["type"] == "update":
                    self.update_labels(
                        msg["date"],
                        msg["baixados"],
                        msg["localizados"],
                        msg["atualizaveis"],
                        msg["em_progresso"],
                        msg["restantes"]
                    )
                    if msg["error"]:
                        self.lbl_erro.config(text=f"Último erro: {msg['error']}")
                elif msg["type"] == "checking_connection":
                    self.btn_action.config(text="Verificando...", state="disabled")
                    self.cb_speed.config(state="disabled")
                    self.lbl_pdf_atual.config(text="Verificando internet e portal...")
                    self.lbl_erro.config(text="")
                elif msg["type"] == "sync_started":
                    self.btn_action.config(text="Pausar", state="normal")
                    self.cb_speed.config(state="disabled")
                elif msg["type"] == "connection_error":
                    has_queue = len(self.state_mgr.data.get("fila_restante", [])) > 0 or len(self.state_mgr.data.get("em_andamento", [])) > 0
                    btn_text = "Retomar" if has_queue else "ATUALIZAR Base de PDFs"
                    self.btn_action.config(text=btn_text, state="normal")
                    self.cb_speed.config(state="readonly")
                    if msg["error_type"] == "internet":
                        msg_err = "Sem conexão ativa com a internet. A base local foi verificada, mas a sincronização online está pausada."
                    else:
                        msg_err = "Portal TJRR indisponível no momento. A base local foi verificada, mas a sincronização online está pausada."
                    if msg.get("error_detail"):
                        msg_err += f"\nDetalhes: {msg['error_detail']}"
                    self.lbl_pdf_atual.config(text="Sincronização online pausada.")
                    self.lbl_erro.config(text=msg_err)
                elif msg["type"] == "portal_unstable":
                    self.btn_action.config(text="Retomar", state="normal")
                    self.cb_speed.config(state="readonly")
                    msg_err = f"Portal TJRR apresentou instabilidade recente ({msg.get('error')}). A sincronização online foi pausada."
                    self.lbl_pdf_atual.config(text="Sincronização online pausada por instabilidade.")
                    self.lbl_erro.config(text=msg_err)
                elif msg["type"] == "done":
                    self.worker.finish()
                    self.btn_action.config(text="Concluído", state="disabled")
                    self.lbl_pdf_atual.config(text="Sincronização concluída!")
                    self.progress_var.set(100.0)
                    self.lbl_pct.config(text="100.00%")
                elif msg["type"] == "done_with_errors":
                    self.worker.finish(clear_state=False)
                    self.btn_action.config(text="Concluído com falhas", state="disabled")
                    self.lbl_pdf_atual.config(text="Sincronização concluída com falhas.")
                    self.lbl_erro.config(
                        text="Algumas datas falharam. Elas serão tentadas novamente na próxima execução."
                    )
                elif msg["type"] == "initial_progress":
                    self.update_initial_progress(msg)
                elif msg["type"] == "initial_ready":
                    self.finish_initial_queue()
                elif msg["type"] == "initial_error":
                    self.fail_initial_queue(msg["error"])
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    def update_speed_label(self):
        current_time = time.time()
        current_bytes = self.worker.total_bytes
        current_processed_dates = self.worker.processed_dates
        
        dt = current_time - self.last_time
        db = current_bytes - self.last_bytes
        processed_delta = current_processed_dates - self.last_processed_dates
        
        if dt > 0:
            speed = db / dt
            dates_per_second = processed_delta / dt
            if speed < 1024:
                txt = f"{speed:.1f} B/s"
            elif speed < 1024 * 1024:
                txt = f"{speed/1024:.1f} KB/s"
            else:
                txt = f"{speed/(1024*1024):.2f} MB/s"
            
            self.lbl_velocidade_real.config(
                text=f"Download: {txt} | Consultas: {dates_per_second:.1f} datas/s"
            )
            
        self.last_bytes = current_bytes
        self.last_processed_dates = current_processed_dates
        self.last_time = current_time
        self.root.after(1000, self.update_speed_label)

    def on_close(self):
        if self.worker.running:
            self.worker.stop()
        self.root.destroy()
