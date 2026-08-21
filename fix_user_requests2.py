import os

search_path = r"c:\Users\f3011542\Documents\GitHub\NewDjeFinder\dje_finder\search.py"
with open(search_path, "r", encoding="utf-8") as f:
    search_content = f.read()

search_content = search_content.replace("PAGE_SIZE = 50", "PAGE_SIZE = 10")
with open(search_path, "w", encoding="utf-8") as f:
    f.write(search_content)


gui_path = r"c:\Users\f3011542\Documents\GitHub\NewDjeFinder\dje_finder\gui.py"
with open(gui_path, "r", encoding="utf-8") as f:
    gui_content = f.read()

# 1. Default Sort Value
gui_content = gui_content.replace('self.search_sort_var = tk.StringVar(value="Relevância")', 'self.search_sort_var = tk.StringVar(value="Mais recentes")')

# 2. Columns config
old_columns = """        columns = ("date", "period", "snippet", "path")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.tag_configure("odd", background="#111827", foreground="#f8fafc")
        self.search_tree.tag_configure("even", background="#172033", foreground="#f8fafc")
        self.search_tree.heading("date", text="Data")
        self.search_tree.heading("period", text="Ano/Mês")
        self.search_tree.heading("snippet", text="Trecho")
        self.search_tree.heading("path", text="Arquivo")
        self.search_tree.column("date", width=90, minwidth=80, stretch=False)
        self.search_tree.column("period", width=80, minwidth=70, stretch=False)
        self.search_tree.column("snippet", width=520, minwidth=260, stretch=True)
        self.search_tree.column("path", width=220, minwidth=120, stretch=True)"""

new_columns = """        columns = ("date", "snippet", "path")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.tag_configure("odd", background="#111827", foreground="#f8fafc")
        self.search_tree.tag_configure("even", background="#172033", foreground="#f8fafc")
        self.search_tree.heading("date", text="Data ▼", command=self.toggle_date_sort)
        self.search_tree.heading("snippet", text="Trecho")
        self.search_tree.heading("path", text="Arquivo")
        self.search_tree.column("date", width=90, minwidth=80, stretch=False)
        self.search_tree.column("snippet", width=520, minwidth=260, stretch=True)
        self.search_tree.column("path", width=220, minwidth=120, stretch=True)"""

gui_content = gui_content.replace(old_columns, new_columns)

# 3. Apply search results
old_insert = """                values=(
                    result.display_date,
                    f"{result.year}/{result.month}",
                    result.snippet,
                    str(result.pdf_path),
                ),"""

new_insert = """                values=(
                    result.display_date,
                    result.snippet,
                    str(result.pdf_path),
                ),"""
gui_content = gui_content.replace(old_insert, new_insert)

# 4. Update on_search_filter_changed to sync arrow, and add toggle_date_sort
old_filter = """    def on_search_filter_changed(self, _event=None):
        if _event == "year" or (_event and getattr(_event, "widget", None) == self.cb_search_year):"""

new_filter = """    def toggle_date_sort(self):
        current_sort = self.search_sort_var.get()
        if current_sort == "Mais recentes":
            new_sort = "Mais antigos"
        else:
            new_sort = "Mais recentes"
            
        self.search_sort_var.set(new_sort)
        self.on_search_filter_changed()

    def on_search_filter_changed(self, _event=None):
        current_sort = self.search_sort_var.get()
        if current_sort == "Mais recentes":
            self.search_tree.heading("date", text="Data ▼")
        elif current_sort == "Mais antigos":
            self.search_tree.heading("date", text="Data ▲")
        else:
            self.search_tree.heading("date", text="Data")
            
        if _event == "year" or (_event and getattr(_event, "widget", None) == self.cb_search_year):"""

gui_content = gui_content.replace(old_filter, new_filter)

with open(gui_path, "w", encoding="utf-8") as f:
    f.write(gui_content)

print("Applied user requested changes.")
