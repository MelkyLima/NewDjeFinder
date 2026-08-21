import os

gui_path = r"c:\Users\f3011542\Documents\GitHub\NewDjeFinder\dje_finder\gui.py"
with open(gui_path, "r", encoding="utf-8") as f:
    gui_content = f.read()

# 1. Update columns definition
old_columns = """        columns = ("date", "snippet", "path")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.tag_configure("odd", background="#111827", foreground="#f8fafc")
        self.search_tree.tag_configure("even", background="#172033", foreground="#f8fafc")
        self.search_tree.heading("date", text="Data ▼", command=self.toggle_date_sort)
        self.search_tree.heading("snippet", text="Trecho")
        self.search_tree.heading("path", text="Arquivo")
        self.search_tree.column("date", width=90, minwidth=80, stretch=False)
        self.search_tree.column("snippet", width=520, minwidth=260, stretch=True)
        self.search_tree.column("path", width=220, minwidth=120, stretch=True)"""

new_columns = """        columns = ("date", "snippet")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.tag_configure("odd", background="#111827", foreground="#f8fafc")
        self.search_tree.tag_configure("even", background="#172033", foreground="#f8fafc")
        self.search_tree.heading("date", text="Data ▼", command=self.toggle_date_sort)
        self.search_tree.heading("snippet", text="Trecho")
        self.search_tree.column("date", width=90, minwidth=80, stretch=False)
        self.search_tree.column("snippet", width=740, minwidth=260, stretch=True)
        
        self.search_tree.bind("<Double-1>", lambda e: self.open_selected_pdf())
        self.search_tree.bind("<Return>", lambda e: self.open_selected_pdf())"""

gui_content = gui_content.replace(old_columns, new_columns)

# 2. Update insert values
old_insert = """                values=(
                    result.display_date,
                    result.snippet,
                    str(result.pdf_path),
                ),"""

new_insert = """                values=(
                    result.display_date,
                    result.snippet,
                ),"""
gui_content = gui_content.replace(old_insert, new_insert)

with open(gui_path, "w", encoding="utf-8") as f:
    f.write(gui_content)

print("Applied user requested changes.")
