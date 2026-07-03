import multiprocessing
import tkinter as tk
from dje_finder.gui import TJRRSyncApp

if __name__ == "__main__":
    multiprocessing.freeze_support()
    root = tk.Tk()
    app = TJRRSyncApp(root)
    root.mainloop()
