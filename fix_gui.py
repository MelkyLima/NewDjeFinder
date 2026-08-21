import re
import os

gui_path = r"c:\Users\f3011542\Documents\GitHub\NewDjeFinder\dje_finder\gui.py"
with open(gui_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update UI layout to put button next to title
old_ui_layout = """        content_frame = ctk.CTkFrame(shell_frame, fg_color=self.colors["window"], corner_radius=0)
        content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=22, pady=(20, 22))

        self.page_title = ctk.CTkLabel(content_frame, text="", text_color="#ffffff", font=(self.font_family, 24, "bold"))
        self.page_title.pack(anchor=tk.W, pady=(0, 4))"""
new_ui_layout = """        content_frame = ctk.CTkFrame(shell_frame, fg_color=self.colors["window"], corner_radius=0)
        content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=22, pady=(20, 22))

        title_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        title_frame.pack(fill=tk.X, anchor=tk.W, pady=(0, 4))
        
        self.btn_action = ctk.CTkButton(
            title_frame,
            text="\\ue72c",
            width=36,
            height=36,
            corner_radius=8,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            font=(self.icon_font_family, 18),
            command=self.toggle_action,
        )
        self.action_state = "ATUALIZAR Base de PDFs"
        self.action_tooltip = Tooltip(self.btn_action, self.action_state)
        self.btn_action.pack(side=tk.LEFT, padx=(0, 10))

        self.page_title = ctk.CTkLabel(title_frame, text="", text_color="#ffffff", font=(self.font_family, 24, "bold"))
        self.page_title.pack(side=tk.LEFT)"""
content = content.replace(old_ui_layout, new_ui_layout)

# 2. Add set_action_state helper right after show_page
old_show_page = """        if page == "search":
            self.entry_search.config(state="normal")
            self.root.after(50, self.entry_search.focus_set)"""
new_show_page = old_show_page + """

    def set_action_state(self, state_name, icon, enabled=True):
        self.action_state = state_name
        self.btn_action.config(text=icon, state="normal" if enabled else "disabled")
        if hasattr(self, "action_tooltip"):
            self.action_tooltip.text = state_name"""
content = content.replace(old_show_page, new_show_page)

# 3. Remove old button initialization
old_btn_init = """        self.btn_action = ctk.CTkButton(
            main_frame,
            text="ATUALIZAR Base de PDFs",
            command=self.toggle_action,
            corner_radius=12,
            height=44,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            font=(self.font_family, 12, "bold"),
        )
        self.btn_action.pack(side=tk.BOTTOM, fill=tk.X, padx=22, pady=(10, 22))"""
content = content.replace(old_btn_init, "")

# 4. Auto-start sync in finish_initial_queue
old_finish = """        self.worker.start_background_indexing()
        self.indexing_in_progress = True"""
new_finish = """        self.worker.start_background_indexing()
        self.indexing_in_progress = True
        
        # Auto start action after initial prep
        self.root.after(500, self.toggle_action)"""
content = content.replace(old_finish, new_finish)

# 5. Replace state configurations
content = content.replace('self.btn_action.config(text="Preparando base local...", state="disabled")', 'self.set_action_state("Preparando base local...", "\\ue895", enabled=False)')
content = content.replace('self.btn_action.config(text="Rechecar Base", state="normal")', 'self.set_action_state("Rechecar Base", "\\ue72c", enabled=True)')
content = content.replace('self.btn_action.config(text="ATUALIZAR Base de PDFs", state="normal")', 'self.set_action_state("ATUALIZAR Base de PDFs", "\\ue72c", enabled=True)')

content = content.replace('txt = self.btn_action.cget("text")', 'txt = self.action_state')
content = content.replace('self.btn_action.config(text="Pausar")', 'self.set_action_state("Pausar", "\\ue769", enabled=True)')
content = content.replace('self.btn_action.config(text="Preparando...", state="disabled")', 'self.set_action_state("Preparando...", "\\ue895", enabled=False)')
content = content.replace('self.btn_action.config(text="Retomar")', 'self.set_action_state("Retomar", "\\ue768", enabled=True)')

content = content.replace('self.btn_action.config(text="Verificando...", state="disabled")', 'self.set_action_state("Verificando...", "\\ue895", enabled=False)')
content = content.replace('self.btn_action.config(text="Pausar", state="normal")', 'self.set_action_state("Pausar", "\\ue769", enabled=True)')

content = content.replace('self.btn_action.config(text=btn_text, state="normal")', 'self.set_action_state(btn_text, "\\ue768" if has_queue else "\\ue72c", enabled=True)')
content = content.replace('self.btn_action.config(text="Retomar", state="normal")', 'self.set_action_state("Retomar", "\\ue768", enabled=True)')

with open(gui_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Updated gui.py successfully")
