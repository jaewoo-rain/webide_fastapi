# gui_app.py
import tkinter as tk

root = tk.Tk()
root.title("Hello GUI")
label = tk.Label(root, text="This is a GUI window!", font=("Arial", 20))
label.pack(padx=20, pady=20)
root.mainloop()
