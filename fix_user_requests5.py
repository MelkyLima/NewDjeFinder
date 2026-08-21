import os

gui_path = r"c:\Users\f3011542\Documents\GitHub\NewDjeFinder\dje_finder\gui.py"
with open(gui_path, "r", encoding="utf-8") as f:
    gui_content = f.read()

# 1. Swap nav buttons order
old_nav = """        self.create_nav_button(sidebar, "sync", "\\ue72c", "Sincronização").pack(fill=tk.X, padx=10, pady=(0, 8))
        self.create_nav_button(sidebar, "search", "\\ue721", "Busca textual").pack(fill=tk.X, padx=10, pady=(0, 8))"""

new_nav = """        self.create_nav_button(sidebar, "search", "\\ue721", "Busca textual").pack(fill=tk.X, padx=10, pady=(0, 8))
        self.create_nav_button(sidebar, "sync", "\\ue72c", "Sincronização").pack(fill=tk.X, padx=10, pady=(0, 8))"""

gui_content = gui_content.replace(old_nav, new_nav)

# 2. Change default page shown at startup
old_default = 'self.show_page("sync")'
new_default = 'self.show_page("search")'

# Only replace the first occurrence which is in setup_ui, not others.
# Actually let's use a targeted replace if there are multiple.
# The one we want to replace is around line 365, inside setup_ui.
if gui_content.count(old_default) >= 1:
    gui_content = gui_content.replace(old_default, new_default, 1)

with open(gui_path, "w", encoding="utf-8") as f:
    f.write(gui_content)

print("Applied user requested changes.")
