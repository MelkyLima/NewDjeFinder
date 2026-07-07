import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from dje_finder.config import APP_NAME, logger
from dje_finder.persistence import IndexManager, StateManager
from dje_finder.search import (
    MATCH_ALL_TERMS,
    MATCH_EXACT_PHRASE,
    MATCH_NEAR_CONTEXT,
    PDFSearchEngine,
    SORT_NEWEST,
    SORT_OLDEST,
    SORT_RELEVANCE,
)
from dje_finder.worker import WorkerController

class TJRRSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("980x760")
        self.root.minsize(820, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.gui_queue = queue.Queue()
        self.index_mgr = IndexManager()
        self.state_mgr = StateManager()
        self.worker = WorkerController(self.index_mgr, self.state_mgr, self.gui_queue)
        self.search_engine = PDFSearchEngine()
        self.initializing = True
        self.indexing_in_progress = False
        self.search_in_progress = False
        self.search_offset = 0
        self.search_query = ""
        self.search_response = None
        self.search_rows = {}
        self.search_request_id = 0
        
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
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        main_frame = ttk.Frame(self.notebook, padding=20)
        search_frame = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(main_frame, text="Sincronização")
        self.notebook.add(search_frame, text="Busca textual")
        
        self.btn_action = ttk.Button(main_frame, text="ATUALIZAR Base de PDFs", command=self.toggle_action)
        self.btn_action.pack(side=tk.BOTTOM, fill=tk.X, ipady=8, pady=(10, 0))
        
        self.lbl_erro = ttk.Label(main_frame, text="", foreground="red", wraplength=900)
        self.lbl_erro.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.lbl_pdf_atual = ttk.Label(main_frame, text="PDF atual: Aguardando...", font=("Segoe UI", 10, "bold"))
        self.lbl_pdf_atual.pack(anchor=tk.W, pady=(0, 10))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))
        
        self.lbl_pct = ttk.Label(main_frame, text="0.00%")
        self.lbl_pct.pack(anchor=tk.E, pady=(0, 15))
        
        info_frame = ttk.LabelFrame(main_frame, text="Estatísticas", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        
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
        
        indexer_frame = ttk.LabelFrame(main_frame, text="Busca Textual (Conteúdo)", padding=10)
        indexer_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.lbl_indexados = ttk.Label(indexer_frame, text="PDFs Indexados para busca: 0")
        self.lbl_indexados.pack(anchor=tk.W, pady=2)
        
        self.lbl_paginas_indexadas = ttk.Label(indexer_frame, text="Total de documentos indexados: 0")
        self.lbl_paginas_indexadas.pack(anchor=tk.W, pady=2)
        
        self.lbl_status_indexador = ttk.Label(indexer_frame, text="Status do buscador: Aguardando...", font=("Segoe UI", 9, "italic"))
        self.lbl_status_indexador.pack(anchor=tk.W, pady=2)
        
        speed_frame = ttk.Frame(main_frame)
        speed_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(speed_frame, text="Modo:").pack(side=tk.LEFT, padx=(0, 10))
        self.cb_speed = ttk.Combobox(speed_frame, values=["1 - Lento (1MB/s)", "2 - Rápido (5MB/s)", "3 - Turbo (Ilimitado)"], state="readonly")
        self.cb_speed.current(1)
        self.cb_speed.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.setup_search_ui(search_frame)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    def setup_search_ui(self, parent):
        top_frame = ttk.Frame(parent)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(top_frame, text="Termo:").pack(side=tk.LEFT, padx=(0, 8))
        self.search_var = tk.StringVar()
        self.entry_search = ttk.Entry(top_frame, textvariable=self.search_var, state="normal")
        self.entry_search.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry_search.bind("<Return>", lambda _event: self.start_search(reset=True))
        self.entry_search.bind("<Button-1>", lambda _event: self.entry_search.focus_set())

        self.btn_search = ttk.Button(top_frame, text="Buscar", command=lambda: self.start_search(reset=True))
        self.btn_search.pack(side=tk.LEFT)

        related_frame = ttk.Frame(parent)
        related_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(related_frame, text="Perto de:").pack(side=tk.LEFT, padx=(0, 8))
        self.search_related_var = tk.StringVar()
        self.entry_search_related = ttk.Entry(related_frame, textvariable=self.search_related_var, state="normal")
        self.entry_search_related.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry_search_related.bind("<Return>", lambda _event: self.start_search(reset=True))
        ttk.Label(related_frame, text="Distância:").pack(side=tk.LEFT, padx=(0, 6))
        self.search_distance_var = tk.StringVar(value="50 palavras")
        self.cb_search_distance = ttk.Combobox(
            related_frame,
            textvariable=self.search_distance_var,
            values=["25 palavras", "50 palavras", "100 palavras", "200 palavras"],
            width=12,
            state="readonly",
        )
        self.cb_search_distance.pack(side=tk.LEFT)
        self.cb_search_distance.bind("<<ComboboxSelected>>", self.on_search_filter_changed)

        filters_frame = ttk.Frame(parent)
        filters_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(filters_frame, text="Ano:").pack(side=tk.LEFT, padx=(0, 6))
        self.search_year_var = tk.StringVar(value="Todos")
        self.cb_search_year = ttk.Combobox(filters_frame, textvariable=self.search_year_var, values=["Todos"], width=14, state="readonly")
        self.cb_search_year.pack(side=tk.LEFT, padx=(0, 12))
        self.cb_search_year.bind("<<ComboboxSelected>>", self.on_search_filter_changed)

        ttk.Label(filters_frame, text="Mês:").pack(side=tk.LEFT, padx=(0, 6))
        self.search_month_var = tk.StringVar(value="Todos")
        self.cb_search_month = ttk.Combobox(filters_frame, textvariable=self.search_month_var, values=["Todos"], width=14, state="readonly")
        self.cb_search_month.pack(side=tk.LEFT, padx=(0, 12))
        self.cb_search_month.bind("<<ComboboxSelected>>", self.on_search_filter_changed)

        ttk.Label(filters_frame, text="Modo:").pack(side=tk.LEFT, padx=(0, 6))
        self.search_match_var = tk.StringVar(value="Todos os termos")
        self.cb_search_match = ttk.Combobox(
            filters_frame,
            textvariable=self.search_match_var,
            values=["Todos os termos", "Frase exata", "Contexto próximo"],
            width=16,
            state="readonly",
        )
        self.cb_search_match.pack(side=tk.LEFT, padx=(0, 12))
        self.cb_search_match.bind("<<ComboboxSelected>>", self.on_search_filter_changed)

        ttk.Label(filters_frame, text="Ordenar:").pack(side=tk.LEFT, padx=(0, 6))
        self.search_sort_var = tk.StringVar(value="Relevância")
        self.cb_search_sort = ttk.Combobox(
            filters_frame,
            textvariable=self.search_sort_var,
            values=["Relevância", "Mais recentes", "Mais antigos"],
            width=16,
            state="readonly",
        )
        self.cb_search_sort.pack(side=tk.LEFT, padx=(0, 12))
        self.cb_search_sort.bind("<<ComboboxSelected>>", self.on_search_filter_changed)

        self.btn_load_more = ttk.Button(filters_frame, text="Carregar mais", command=lambda: self.start_search(reset=False), state="disabled")
        self.btn_load_more.pack(side=tk.RIGHT)

        self.lbl_search_summary = ttk.Label(parent, text="Digite um termo para buscar nos PDFs indexados.")
        self.lbl_search_summary.pack(fill=tk.X, pady=(0, 4))

        self.lbl_search_warning = ttk.Label(parent, text="", foreground="#a15c00", wraplength=920)
        self.lbl_search_warning.pack(fill=tk.X, pady=(0, 8))

        table_frame = ttk.Frame(parent)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("date", "period", "snippet", "path")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.heading("date", text="Data")
        self.search_tree.heading("period", text="Ano/Mês")
        self.search_tree.heading("snippet", text="Trecho")
        self.search_tree.heading("path", text="Arquivo")
        self.search_tree.column("date", width=90, minwidth=80, stretch=False)
        self.search_tree.column("period", width=80, minwidth=70, stretch=False)
        self.search_tree.column("snippet", width=520, minwidth=260, stretch=True)
        self.search_tree.column("path", width=220, minwidth=120, stretch=True)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.search_tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.search_tree.xview)
        self.search_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.search_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        actions_frame = ttk.Frame(parent)
        actions_frame.pack(fill=tk.X, pady=(10, 0))
        self.btn_open_pdf = ttk.Button(actions_frame, text="Abrir PDF", command=self.open_selected_pdf)
        self.btn_open_pdf.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_open_folder = ttk.Button(actions_frame, text="Abrir pasta", command=self.open_selected_folder)
        self.btn_open_folder.pack(side=tk.LEFT)

    def start_search(self, reset=True):
        query = self.search_var.get().strip()
        if not reset and self.search_query:
            query = self.search_query
        if not query:
            self.lbl_search_summary.config(text="Digite um termo para iniciar a busca.")
            self.lbl_search_warning.config(text="")
            return
        if self.search_in_progress:
            return

        if reset:
            self.search_offset = 0
            self.search_query = query
            self.search_rows = {}
            for item in self.search_tree.get_children():
                self.search_tree.delete(item)
        elif self.search_response:
            self.search_offset = self.search_response.offset + len(self.search_response.results)
            self.search_query = query

        year = self._selected_filter_value(self.search_year_var.get(), 4)
        month = self._selected_filter_value(self.search_month_var.get(), 2)
        sort = self._selected_sort()
        match_mode = self._selected_match_mode()
        related_query = self.search_related_var.get().strip()
        context_distance = self._selected_context_distance()
        if related_query:
            match_mode = MATCH_NEAR_CONTEXT
        offset = self.search_offset
        self.search_in_progress = True
        self.search_request_id += 1
        request_id = self.search_request_id
        self.btn_search.config(state="disabled")
        self.btn_load_more.config(state="disabled")
        self.lbl_search_summary.config(text="Buscando...")
        self.lbl_search_warning.config(text="")

        threading.Thread(
            target=self._run_search,
            args=(request_id, query, year, month, sort, offset, match_mode, related_query, context_distance),
            daemon=True,
        ).start()

    def on_search_filter_changed(self, _event=None):
        if self.search_var.get().strip() and not self.search_in_progress:
            self.start_search(reset=True)

    def _run_search(self, request_id, query, year, month, sort, offset, match_mode, related_query, context_distance):
        try:
            response = self.search_engine.search(
                query,
                year=year,
                month=month,
                sort=sort,
                offset=offset,
                match_mode=match_mode,
                related_query=related_query,
                context_distance=context_distance,
            )
            self.gui_queue.put({"type": "search_results", "request_id": request_id, "response": response})
        except Exception as error:
            logger.exception("Erro ao executar busca textual.")
            self.gui_queue.put({"type": "search_error", "request_id": request_id, "error": str(error)})

    def apply_search_results(self, response):
        self.search_response = response
        self.search_offset = response.offset
        for result in response.results:
            iid = result.date_str
            suffix = 1
            while iid in self.search_rows:
                suffix += 1
                iid = f"{result.date_str}-{suffix}"
            self.search_rows[iid] = result
            self.search_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    result.display_date,
                    f"{result.year}/{result.month}",
                    result.snippet,
                    str(result.pdf_path),
                ),
            )

        visible = len(self.search_rows)
        if response.total == 0:
            self.lbl_search_summary.config(text="Nenhum resultado encontrado.")
        else:
            self.lbl_search_summary.config(text=f"Exibindo {visible} de {response.total} resultado(s).")

        if response.has_pending_indexing:
            pending = response.total_pdfs - response.indexed_pdfs
            self.lbl_search_warning.config(
                text=f"Aviso: ainda existem {pending} PDF(s) pendente(s) de indexação. A busca pode não cobrir toda a base."
            )
        else:
            self.lbl_search_warning.config(text="")

        self.btn_load_more.config(state="normal" if response.has_more else "disabled")
        self._refresh_filter_values(response)

    def apply_search_error(self, error):
        self.lbl_search_summary.config(text="Não foi possível concluir a busca.")
        self.lbl_search_warning.config(text=error)

    def finish_search_state(self):
        self.search_in_progress = False
        self.entry_search.config(state="normal")
        self.btn_search.config(state="normal")
        if self.search_response and self.search_response.has_more:
            self.btn_load_more.config(state="normal")

    def on_tab_changed(self, _event):
        selected_tab = self.notebook.tab(self.notebook.select(), "text")
        if selected_tab == "Busca textual":
            self.entry_search.config(state="normal")
            self.root.after(50, self.entry_search.focus_set)

    def _refresh_filter_values(self, response):
        current_year = self.search_year_var.get()
        current_month = self.search_month_var.get()
        year_values = ["Todos"] + [f"{year} ({count})" for year, count in sorted(response.year_counts.items(), reverse=True)]
        month_values = ["Todos"] + [f"{month} ({count})" for month, count in sorted(response.month_counts.items())]
        self.cb_search_year.config(values=year_values)
        self.cb_search_month.config(values=month_values)
        current_year_value = self._selected_filter_value(current_year, 4)
        if current_year in year_values:
            self.search_year_var.set(current_year)
        elif current_year_value in response.year_counts:
            self.search_year_var.set(next(value for value in year_values if value.startswith(current_year_value)))
        else:
            self.search_year_var.set("Todos")
        current_month_value = self._selected_filter_value(current_month, 2)
        if current_month in month_values:
            self.search_month_var.set(current_month)
        elif current_month_value in response.month_counts:
            self.search_month_var.set(next(value for value in month_values if value.startswith(current_month_value)))
        else:
            self.search_month_var.set("Todos")

    def _selected_filter_value(self, value, size):
        if not value or value == "Todos":
            return None
        prefix = value.strip()[:size]
        return prefix if prefix.isdigit() else None

    def _selected_sort(self):
        label = self.search_sort_var.get()
        if label == "Mais recentes":
            return SORT_NEWEST
        if label == "Mais antigos":
            return SORT_OLDEST
        return SORT_RELEVANCE

    def _selected_match_mode(self):
        if self.search_match_var.get() == "Contexto próximo":
            return MATCH_NEAR_CONTEXT
        if self.search_match_var.get() == "Frase exata":
            return MATCH_EXACT_PHRASE
        return MATCH_ALL_TERMS

    def _selected_context_distance(self):
        value = self.search_distance_var.get().split(" ", 1)[0]
        try:
            return int(value)
        except ValueError:
            return 50

    def get_selected_search_result(self):
        selection = self.search_tree.selection()
        if not selection:
            messagebox.showinfo("Busca textual", "Selecione um resultado primeiro.")
            return None
        return self.search_rows.get(selection[0])

    def open_selected_pdf(self):
        result = self.get_selected_search_result()
        if result:
            self.open_path(result.pdf_path)

    def open_selected_folder(self):
        result = self.get_selected_search_result()
        if result:
            self.open_path(result.pdf_path.parent)

    def open_path(self, path):
        path = os.fspath(path)
        if not os.path.exists(path):
            messagebox.showwarning("Busca textual", "O arquivo ou pasta não existe mais no local esperado.")
            return
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as error:
            messagebox.showerror("Busca textual", f"Não foi possível abrir o caminho:\n{error}")

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
        self.cb_speed.config(state="readonly")
        
        self.update_labels(
            pdf="",
            baixados=self.state_mgr.data.get("baixados", 0),
            localizados=self.state_mgr.data.get("localizados", 0),
            atualizaveis=self.state_mgr.data.get("atualizaveis", 0),
            em_progresso=0,
            restantes=len(self.state_mgr.data.get("fila_restante", []))
        )
        
        if self.state_mgr.data.get("atualizaveis", 0) == 0 and self.state_mgr.data.get("localizados", 0) > 0:
            self.btn_action.config(text="Rechecar Base", state="normal")
            self.lbl_pdf_atual.config(text=self.get_finished_text())
            self.progress_var.set(100.0)
            self.lbl_pct.config(text="100.00%")
        else:
            self.btn_action.config(text="ATUALIZAR Base de PDFs", state="normal")
            self.lbl_pdf_atual.config(text="PDF atual: Aguardando...")
            
        self.worker.start_background_indexing()
        self.indexing_in_progress = True

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
        if txt in ("ATUALIZAR Base de PDFs", "Rechecar Base"):
            self.btn_action.config(text="Pausar")
            self.cb_speed.config(state="disabled")
            
            if txt == "Rechecar Base":
                self.btn_action.config(text="Preparando...", state="disabled")
                self.lbl_pdf_atual.config(text="PDF atual: Rechecando base...")
                threading.Thread(target=self._rebuild_and_start, args=(speed_cfg,), daemon=True).start()
            else:
                self.worker.start(speed_cfg)
        elif txt == "Pausar":
            self.btn_action.config(text="Retomar")
            self.cb_speed.config(state="readonly")
            self.worker.pause()
        elif txt == "Retomar":
            self.btn_action.config(text="Pausar")
            self.cb_speed.config(state="disabled")
            self.worker.resume(speed_cfg)

    def _rebuild_and_start(self, speed_cfg):
        try:
            self.worker.build_queue()
        except Exception as error:
            logger.exception("Não foi possível rechecar a base.")
            self.gui_queue.put({"type": "initial_error", "error": str(error)})
            return
        self.gui_queue.put({"type": "recheck_ready", "speed_cfg": speed_cfg})

    def get_finished_text(self):
        last_date = self.index_mgr.data.get("ultima_data_indexada", "")
        if last_date and len(last_date) == 8:
            return f"Base de Dados atualizada ({last_date[6:8]}/{last_date[4:6]}/{last_date[0:4]})"
        return "Base de Dados atualizada"

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
                    self.btn_action.config(text="Rechecar Base", state="normal")
                    self.cb_speed.config(state="readonly")
                    self.lbl_pdf_atual.config(text=self.get_finished_text())
                    self.progress_var.set(100.0)
                    self.lbl_pct.config(text="100.00%")
                elif msg["type"] == "recheck_ready":
                    atualizaveis = self.state_mgr.data.get("atualizaveis", 0)
                    self.update_labels(
                        pdf="",
                        baixados=self.state_mgr.data.get("baixados", 0),
                        localizados=self.state_mgr.data.get("localizados", 0),
                        atualizaveis=atualizaveis,
                        em_progresso=0,
                        restantes=len(self.state_mgr.data.get("fila_restante", []))
                    )
                    if atualizaveis > 0:
                        self.btn_action.config(text="Pausar", state="normal")
                        self.worker.start(msg["speed_cfg"])
                    else:
                        self.btn_action.config(text="Rechecar Base", state="normal")
                        self.cb_speed.config(state="readonly")
                        self.lbl_pdf_atual.config(text=self.get_finished_text())
                        self.progress_var.set(100.0)
                        self.lbl_pct.config(text="100.00%")
                elif msg["type"] == "done_with_errors":
                    self.worker.finish(clear_state=False)
                    self.btn_action.config(text="Rechecar Base", state="normal")
                    self.cb_speed.config(state="readonly")
                    self.lbl_pdf_atual.config(text="PDF atual: Concluído com falhas.")
                    self.lbl_erro.config(
                        text="Algumas datas falharam. Clique em 'Rechecar Base' para tentar novamente."
                    )
                elif msg["type"] == "initial_progress":
                    self.update_initial_progress(msg)
                elif msg["type"] == "initial_ready":
                    self.finish_initial_queue()
                elif msg["type"] == "initial_error":
                    self.fail_initial_queue(msg["error"])
                elif msg["type"] == "index_progress":
                    current = msg["current"]
                    total = msg["total"]
                    last_date = msg["last_date"]
                    stats = msg["stats"]
                    eta_str = self.format_time(msg["eta"])
                    speed = msg["speed"]
                    self.lbl_indexados.config(
                        text=f"PDFs Indexados para busca: {stats['total_indexados']}/{stats['total_baixados']}"
                    )
                    self.lbl_paginas_indexadas.config(
                        text=f"Total de documentos indexados: {stats['total_paginas']}"
                    )
                    if total > 0:
                        if current == 0:
                            self.lbl_status_indexador.config(
                                text="Status: Iniciando indexação em segundo plano dos PDFs pendentes..."
                            )
                        else:
                            self.lbl_status_indexador.config(
                                text=f"Status: Indexando {current}/{total} ({speed:.1f} PDF/s) | ETA: {eta_str}"
                            )
                    else:
                        self.lbl_status_indexador.config(text="Status: Nenhum PDF pendente de indexação.")
                elif msg["type"] == "index_done":
                    stats = msg["stats"]
                    self.indexing_in_progress = False
                    self.lbl_indexados.config(
                        text=f"PDFs Indexados para busca: {stats['total_indexados']}/{stats['total_baixados']}"
                    )
                    self.lbl_paginas_indexadas.config(
                        text=f"Total de documentos indexados: {stats['total_paginas']}"
                    )
                    self.lbl_status_indexador.config(text="Status: Indexação em segundo plano concluída.")
                elif msg["type"] == "search_results":
                    if msg["request_id"] == self.search_request_id:
                        self.apply_search_results(msg["response"])
                        self.finish_search_state()
                elif msg["type"] == "search_error":
                    if msg["request_id"] == self.search_request_id:
                        self.apply_search_error(msg["error"])
                        self.finish_search_state()
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
            
            restantes = len(self.worker.fila) + len(self.worker.active_futures)
            if restantes > 0 and dates_per_second > 0:
                eta_sec = restantes / dates_per_second
                eta_str = self.format_time(eta_sec)
                eta_txt = f" | ETA: {eta_str}"
            elif restantes > 0:
                eta_txt = " | ETA: calculando..."
            else:
                eta_txt = ""

            self.lbl_velocidade_real.config(
                text=f"Download: {txt} | Consultas: {dates_per_second:.1f} datas/s{eta_txt}"
            )
            
        self.last_bytes = current_bytes
        self.last_processed_dates = current_processed_dates
        self.last_time = current_time
        self.root.after(1000, self.update_speed_label)

    def format_time(self, seconds):
        if seconds is None or seconds <= 0:
            return "calculando..."
        s = int(seconds)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h > 0:
            return f"{h:02d}h {m:02d}m {sec:02d}s"
        return f"{m:02d}m {sec:02d}s"

    def on_close(self):
        if self.indexing_in_progress:
            resposta = messagebox.askyesno(
                "Indexação em andamento",
                "A indexação de PDFs para busca textual ainda está em andamento.\n\n"
                "Se fechar agora, o processo será interrompido e retomado "
                "na próxima vez que o aplicativo for aberto.\n\n"
                "Deseja fechar mesmo assim?",
                icon="warning"
            )
            if not resposta:
                return  # Usuário escolheu não fechar

        # Para o download e sinaliza o indexador para interromper
        if self.worker.running:
            self.worker.stop()
        self.worker.stop_indexing()

        # Destrói a janela e encerra o processo por completo.
        # os._exit(0) é necessário porque ThreadPoolExecutor cria threads
        # não-daemon que manteriam o processo Python vivo após root.destroy().
        self.root.destroy()
        os._exit(0)
