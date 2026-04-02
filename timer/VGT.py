import tkinter as tk
from tkinter import ttk, messagebox
import datetime
import threading
import pytz
import time
import os

# ─── Lecture MP3 ──────────────────────────────────────────────────────────────
try:
    from pygame import mixer
    mixer.init()
    USE_PYGAME = True
except ImportError:
    USE_PYGAME = False
    print("pygame non installé — pip install pygame")

def play_mp3(file_path):
    if not USE_PYGAME:
        return
    if not os.path.isfile(file_path):
        print(f"Fichier introuvable : {file_path}")
        return
    def inner():
        try:
            mixer.music.load(file_path)
            mixer.music.play()
        except Exception as e:
            print(f"Erreur lecture MP3 : {e}")
    threading.Thread(target=inner, daemon=True).start()

# ─── Horaires ─────────────────────────────────────────────────────────────────
heure_sons_default = {
    "14:00": "start.mp3",
    "14:45": "45.mp3",
    "14:50": "50.mp3",
    "14:55": "55.mp3",
    "14:58": "58.mp3",
    "15:45": "45.mp3",
    "15:50": "50.mp3",
    "15:55": "55.mp3",
    "15:58": "58.mp3",
    "16:45": "45.mp3",
    "16:50": "50.mp3",
    "16:55": "55.mp3",
    "16:58": "58.mp3",
    "17:45": "45.mp3",
    "17:50": "50.mp3",
    "17:55": "55.mp3",
    "17:58": "end.mp3",
}
heure_sons = dict(heure_sons_default)

# ─── État ─────────────────────────────────────────────────────────────────────
parlees = set()
rappel_count = 0

# ─── Palette ──────────────────────────────────────────────────────────────────
BG         = "#1e1e1e"
BG2        = "#2a2a2a"
FG         = "#e0e0e0"
FG_DIM     = "#888888"
ACCENT     = "#c0392b"
TITLEBAR_H = 32
FONT_TITLE = ("Consolas", 11, "bold")
FONT_CLOCK = ("Consolas", 36, "bold")
FONT_MONO  = ("Consolas", 10)
FONT_SMALL = ("Consolas", 9)

# ─── Boucle heure ─────────────────────────────────────────────────────────────
def boucle_heure():
    global rappel_count
    while True:
        paris = pytz.timezone('Europe/Paris')
        maintenant = datetime.datetime.now(paris)
        heure_affichee = maintenant.strftime("%H:%M:%S")
        heure_rappel   = maintenant.strftime("%H:%M")

        root.after(0, heure_label.config, {'text': heure_affichee})

        if heure_rappel in heure_sons and heure_rappel not in parlees:
            son = heure_sons[heure_rappel]
            play_mp3(son)
            parlees.add(heure_rappel)
            rappel_count += 1
            root.after(0, on_rappel, heure_rappel, son)

        time.sleep(1)

def on_rappel(heure, son):
    log_listbox.insert(tk.END, f"  {heure}   {son}")
    log_listbox.see(tk.END)
    compteur_label.config(text=f"Rappels : {rappel_count}")
    flash_animation()

# ─── Flash ────────────────────────────────────────────────────────────────────
FLASH_SEQ = ["#1e1e1e", "#c0392b", "#1e1e1e", "#c0392b", "#1e1e1e"]
flash_step = [0]

def flash_animation():
    flash_step[0] = 0
    _flash()

def _flash():
    if flash_step[0] < len(FLASH_SEQ):
        c = FLASH_SEQ[flash_step[0]]
        content_frame.configure(bg=c)
        for w in flash_widgets:
            try:
                w.configure(bg=c)
            except Exception:
                pass
        flash_step[0] += 1
        root.after(180, _flash)
    else:
        content_frame.configure(bg=BG)
        for w in flash_widgets:
            try:
                w.configure(bg=BG)
            except Exception:
                pass

# ─── Éditeur d'horaires ───────────────────────────────────────────────────────
def open_editor():
    editor = tk.Toplevel(root)
    editor.title("Horaires")
    editor.geometry("400x460")
    editor.configure(bg=BG)
    editor.resizable(False, False)

    tk.Label(editor, text="Horaires de rappel", font=FONT_TITLE,
             fg=FG, bg=BG).pack(pady=(14, 6))

    frame = tk.Frame(editor, bg=BG)
    frame.pack(fill=tk.BOTH, expand=True, padx=16)

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Dark.Treeview", background=BG2, foreground=FG,
                    fieldbackground=BG2, rowheight=24, font=FONT_MONO)
    style.configure("Dark.Treeview.Heading", background="#333", foreground=FG, font=FONT_MONO)

    cols = ("Heure", "Fichier")
    tree = ttk.Treeview(frame, columns=cols, show="headings", height=12, style="Dark.Treeview")
    for col, w in zip(cols, [120, 220]):
        tree.heading(col, text=col)
        tree.column(col, width=w, anchor="center")
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh():
        tree.delete(*tree.get_children())
        for h, s in sorted(heure_sons.items()):
            tree.insert("", tk.END, values=(h, s))
    refresh()

    form = tk.Frame(editor, bg=BG)
    form.pack(pady=10)

    tk.Label(form, text="HH:MM", fg=FG_DIM, bg=BG, font=FONT_MONO).grid(row=0, column=0, padx=4)
    h_entry = tk.Entry(form, width=8, bg=BG2, fg=FG, insertbackground=FG,
                       relief="flat", font=FONT_MONO)
    h_entry.grid(row=0, column=1, padx=4)

    tk.Label(form, text="fichier.mp3", fg=FG_DIM, bg=BG, font=FONT_MONO).grid(row=0, column=2, padx=4)
    s_entry = tk.Entry(form, width=12, bg=BG2, fg=FG, insertbackground=FG,
                       relief="flat", font=FONT_MONO)
    s_entry.grid(row=0, column=3, padx=4)

    def add():
        h = h_entry.get().strip()
        s = s_entry.get().strip()
        if not h or not s:
            messagebox.showwarning("Champs vides", "Remplissez l'heure et le fichier.", parent=editor)
            return
        try:
            datetime.datetime.strptime(h, "%H:%M")
        except ValueError:
            messagebox.showerror("Format invalide", "Format attendu : HH:MM", parent=editor)
            return
        heure_sons[h] = s
        parlees.discard(h)
        refresh()
        h_entry.delete(0, tk.END)
        s_entry.delete(0, tk.END)

    def delete():
        for item in tree.selection():
            h = tree.item(item)["values"][0]
            heure_sons.pop(h, None)
        refresh()

    def reset():
        heure_sons.clear()
        heure_sons.update(heure_sons_default)
        parlees.clear()
        refresh()

    btn_row = tk.Frame(editor, bg=BG)
    btn_row.pack(pady=6)
    for txt, cmd, col in [("Ajouter", add, "#27ae60"),
                           ("Supprimer", delete, ACCENT),
                           ("Réinitialiser", reset, "#555")]:
        tk.Button(btn_row, text=txt, command=cmd, bg=col, fg="white",
                  font=FONT_MONO, relief="flat", padx=10, pady=4).pack(side=tk.LEFT, padx=6)

# ─── GUI ──────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.overrideredirect(True)          # supprime la barre système
root.configure(bg=BG)
root.resizable(False, False)

WIN_W, WIN_H = 420, 360
sw = root.winfo_screenwidth()
sh = root.winfo_screenheight()
root.geometry(f"{WIN_W}x{WIN_H}+{(sw-WIN_W)//2}+{(sh-WIN_H)//2}")

# ── Barre de titre custom ─────────────────────────────────────────────────────
titlebar = tk.Frame(root, bg=ACCENT, height=TITLEBAR_H)
titlebar.pack(fill=tk.X, side=tk.TOP)
titlebar.pack_propagate(False)

tk.Label(titlebar, text="  VIDEO GAME TIMER", font=FONT_TITLE,
         fg="white", bg=ACCENT, anchor="w").pack(side=tk.LEFT, fill=tk.Y)

close_btn = tk.Label(titlebar, text="  ✕  ", font=("Consolas", 12, "bold"),
                     fg="white", bg=ACCENT, cursor="hand2")
close_btn.pack(side=tk.RIGHT, fill=tk.Y)
close_btn.bind("<Button-1>", lambda e: root.destroy())
close_btn.bind("<Enter>",    lambda e: close_btn.configure(bg="#8b0000"))
close_btn.bind("<Leave>",    lambda e: close_btn.configure(bg=ACCENT))

# Drag
_drag = {"x": 0, "y": 0}
def on_drag_start(e):
    _drag["x"] = e.x
    _drag["y"] = e.y
def on_drag_motion(e):
    dx = e.x - _drag["x"]
    dy = e.y - _drag["y"]
    x = root.winfo_x() + dx
    y = root.winfo_y() + dy
    root.geometry(f"+{x}+{y}")

titlebar.bind("<ButtonPress-1>",   on_drag_start)
titlebar.bind("<B1-Motion>",       on_drag_motion)

# ── Contenu ───────────────────────────────────────────────────────────────────
content_frame = tk.Frame(root, bg=BG)
content_frame.pack(fill=tk.BOTH, expand=True)

# Horloge
heure_label = tk.Label(content_frame, text="--:--:--", font=FONT_CLOCK, fg=FG, bg=BG)
heure_label.pack(pady=(20, 0))

# Compteur
compteur_label = tk.Label(content_frame, text="Rappels : 0", font=FONT_MONO, fg=FG_DIM, bg=BG)
compteur_label.pack()

# Bouton éditeur
tk.Button(content_frame, text="Éditeur d'horaires", command=open_editor,
          bg=BG2, fg=FG, font=FONT_MONO, relief="flat",
          padx=16, pady=6, cursor="hand2").pack(pady=(14, 4))

# Séparateur
tk.Frame(content_frame, bg="#333", height=1).pack(fill=tk.X, padx=20, pady=8)

# Log
log_listbox = tk.Listbox(content_frame, height=6, font=FONT_SMALL,
                          bg="#141414", fg="#aaa", selectbackground=ACCENT,
                          relief="flat", borderwidth=0)
log_listbox.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 14))

# Widgets flashés
flash_widgets = [heure_label, compteur_label, content_frame]

# Thread
threading.Thread(target=boucle_heure, daemon=True).start()

root.mainloop()
