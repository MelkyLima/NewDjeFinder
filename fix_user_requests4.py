import os

gui_path = r"c:\Users\f3011542\Documents\GitHub\NewDjeFinder\dje_finder\gui.py"
with open(gui_path, "r", encoding="utf-8") as f:
    gui_content = f.read()

# 1. Update window minsize just in case, to allow smaller screens
gui_content = gui_content.replace('self.root.minsize(980, 640)', 'self.root.minsize(980, 600)')

# 2. We need to move actions_frame creation BEFORE table_frame pack so we can pack actions_frame with side=tk.BOTTOM first.
# Wait, actually we can just find where actions_frame is created, and move it up before table_frame is packed.
# Or we can just change how we pack them.
# Let's replace the whole block from table_frame creation to actions_frame pack.

old_block = """        table_frame = ctk.CTkFrame(
            parent,
            fg_color="#111827",
            corner_radius=16,
            border_width=1,
            border_color=self.colors["border"],
        )
        table_frame.pack(fill=tk.BOTH, expand=True, padx=22, pady=(0, 0))

        columns = ("date", "snippet")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.tag_configure("odd", background="#111827", foreground="#f8fafc")
        self.search_tree.tag_configure("even", background="#172033", foreground="#f8fafc")
        self.search_tree.heading("date", text="Data ▼", command=self.toggle_date_sort)
        self.search_tree.heading("snippet", text="Trecho")
        self.search_tree.column("date", width=90, minwidth=80, stretch=False)
        self.search_tree.column("snippet", width=740, minwidth=260, stretch=True)
        
        self.search_tree.bind("<Double-1>", lambda e: self.open_selected_pdf())
        self.search_tree.bind("<Return>", lambda e: self.open_selected_pdf())

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.search_tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.search_tree.xview)
        self.search_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.search_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        actions_frame = ctk.CTkFrame(parent, fg_color="transparent")
        actions_frame.pack(fill=tk.X, padx=22, pady=(10, 22))"""

new_block = """        actions_frame = ctk.CTkFrame(parent, fg_color="transparent")
        actions_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=22, pady=(10, 22))

        table_frame = ctk.CTkFrame(
            parent,
            fg_color="#111827",
            corner_radius=16,
            border_width=1,
            border_color=self.colors["border"],
        )
        table_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=22, pady=(0, 0))

        columns = ("date", "snippet")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.tag_configure("odd", background="#111827", foreground="#f8fafc")
        self.search_tree.tag_configure("even", background="#172033", foreground="#f8fafc")
        self.search_tree.heading("date", text="Data ▼", command=self.toggle_date_sort)
        self.search_tree.heading("snippet", text="Trecho")
        self.search_tree.column("date", width=90, minwidth=80, stretch=False)
        self.search_tree.column("snippet", width=740, minwidth=260, stretch=True)
        
        self.search_tree.bind("<Double-1>", lambda e: self.open_selected_pdf())
        self.search_tree.bind("<Return>", lambda e: self.open_selected_pdf())

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.search_tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.search_tree.xview)
        self.search_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.search_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)"""

if old_block in gui_content:
    gui_content = gui_content.replace(old_block, new_block)
else:
    print("WARNING: Could not find block to replace.")

with open(gui_path, "w", encoding="utf-8") as f:
    f.write(gui_content)

print("Applied user requested changes.")
