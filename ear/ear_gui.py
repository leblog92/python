import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
from datetime import datetime
import os
import pygame

# ─────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────
BG        = "#1e1e2e"   # deep navy
PANEL     = "#27273a"   # slightly lighter for panels
BORDER    = "#3a3a52"   # subtle border
FG        = "#cdd6f4"   # soft white text
FG_DIM    = "#6c7086"   # muted labels
ACCENT    = "#89b4fa"   # blue
SUCCESS   = "#a6e3a1"   # green
ERROR     = "#f38ba8"   # red
WARN      = "#fab387"   # orange
GOLD      = "#f9e2af"   # yellow — detected words
MAUVE     = "#cba6f7"   # purple — commands

FONT_TITLE  = ("Segoe UI", 18, "bold")
FONT_BODY   = ("Segoe UI", 10)
FONT_SMALL  = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 10)
FONT_STAT   = ("Segoe UI", 11, "bold")


class VoiceAssistantGUI:

    def __init__(self, voice_recognizer):
        self.recognizer = voice_recognizer
        self.message_queue = queue.Queue()

        # Stats
        self.command_count  = 0
        self.error_count    = 0
        self.word_count     = 0
        self.start_time     = datetime.now()

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry("980x700")
        self.root.minsize(800, 580)
        self.root.configure(bg=BG)

        # Allow dragging the frameless window
        self._drag_x = 0
        self._drag_y = 0

        self._setup_ttk_style()
        self._build_ui()
        self._connect_callbacks()

        self.check_queue()
        self._tick_uptime()

        # Auto-start after 1 s
        self.root.after(1000, self.start_listening)

    # ──────────────────────────────────────────
    # ttk style
    # ──────────────────────────────────────────
    def _setup_ttk_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Buttons — default (grey)
        style.configure("EAR.TButton",
            font=FONT_BODY,
            padding=(10, 6),
            background=PANEL,
            foreground=FG,
            bordercolor=BORDER,
            focuscolor=BORDER,
            relief="flat"
        )
        style.map("EAR.TButton",
            background=[("active", BORDER), ("pressed", BORDER)],
            foreground=[("active", FG)]
        )

        # Primary button (Start/Stop) — blue accent
        style.configure("Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(12, 8),
            background=ACCENT,
            foreground="#11111b",
            bordercolor=ACCENT,
            focuscolor=ACCENT,
            relief="flat"
        )
        style.map("Primary.TButton",
            background=[("active", "#74c7ec"), ("pressed", "#74c7ec")]
        )

        # Danger button (stop) — red
        style.configure("Danger.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(12, 8),
            background=ERROR,
            foreground="#11111b",
            bordercolor=ERROR,
            focuscolor=ERROR,
            relief="flat"
        )
        style.map("Danger.TButton",
            background=[("active", "#eba0ac"), ("pressed", "#eba0ac")]
        )

        # Separator
        style.configure("TSeparator", background=BORDER)

    # ──────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────
    def _build_ui(self):
        self._build_titlebar()
        self._build_body()
        self._build_statusbar()

    # — Title bar ——————————————————————————————
    def _build_titlebar(self):
        bar = tk.Frame(self.root, bg=PANEL, height=54)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # Drag-to-move bindings on the whole bar
        bar.bind("<ButtonPress-1>", self._drag_start)
        bar.bind("<B1-Motion>",     self._drag_move)

        tk.Label(bar, text="EAR", font=("Segoe UI", 16, "bold"),
                 fg=ACCENT, bg=PANEL).pack(side="left", padx=(18, 4), pady=12)
        tk.Label(bar, text="Enhanced Audio Recognition", font=("Segoe UI", 11),
                 fg=FG_DIM, bg=PANEL).pack(side="left", pady=12)

        # Close button (×) — far right
        close_btn = tk.Label(bar, text="×", font=("Segoe UI", 18),
                             fg=FG_DIM, bg=PANEL, cursor="hand2", padx=14)
        close_btn.pack(side="right")
        close_btn.bind("<Enter>",   lambda e: close_btn.config(fg=ERROR))
        close_btn.bind("<Leave>",   lambda e: close_btn.config(fg=FG_DIM))
        close_btn.bind("<Button-1>",lambda e: self._on_close())

        # Status pill
        self._status_frame = tk.Frame(bar, bg=PANEL)
        self._status_frame.pack(side="right", padx=12)

        self._status_dot = tk.Label(self._status_frame, text="●",
                                    font=("Segoe UI", 11), fg=FG_DIM, bg=PANEL)
        self._status_dot.pack(side="left")

        self._status_text = tk.Label(self._status_frame, text="Idle",
                                     font=FONT_BODY, fg=FG_DIM, bg=PANEL)
        self._status_text.pack(side="left", padx=(4, 0))

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # — Body (sidebar + log) ——————————————————
    def _build_body(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(10, 0))

        self._build_sidebar(body)
        self._build_log_panel(body)

    # — Sidebar ————————————————————————————————
    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=PANEL, width=200)
        side.pack(side="left", fill="y", padx=(0, 10))
        side.pack_propagate(False)

        def _btn(text, cmd, style="EAR.TButton"):
            ttk.Button(side, text=text, style=style, command=cmd).pack(
                fill="x", padx=12, pady=2
            )

        # ── Controls ──────────────────────────
        tk.Label(side, text="CONTROLS", font=("Segoe UI", 8, "bold"),
                 fg=FG_DIM, bg=PANEL).pack(anchor="w", padx=14, pady=(14, 4))

        self.listen_btn = ttk.Button(side, text="▶  Start Listening",
                                     style="Primary.TButton",
                                     command=self.toggle_listening)
        self.listen_btn.pack(fill="x", padx=12, pady=(0, 4))

        _btn("Calibrate Microphone", self.calibrate_mic)
        _btn("Sound Test",           self.test_audio)

        ttk.Separator(side).pack(fill="x", padx=12, pady=8)

        # ── Reload ────────────────────────────
        tk.Label(side, text="RELOAD", font=("Segoe UI", 8, "bold"),
                 fg=FG_DIM, bg=PANEL).pack(anchor="w", padx=14, pady=(0, 4))

        _btn("keywords.txt",    self.reload_keywords)
        _btn("actions.ini",     self.reload_actions)
        _btn("config.ini",      self.reload_config)

        ttk.Separator(side).pack(fill="x", padx=12, pady=8)

        # ── Tools ─────────────────────────────
        tk.Label(side, text="TOOLS", font=("Segoe UI", 8, "bold"),
                 fg=FG_DIM, bg=PANEL).pack(anchor="w", padx=14, pady=(0, 4))

        _btn("Measure Threshold", self.measure_threshold)
        _btn("Clear Log",         self.clear_log)

        # ── Separator ──────────────────────────
        ttk.Separator(side).pack(fill="x", padx=12, pady=12)

        # ── Session stats ──────────────────────
        tk.Label(side, text="SESSION", font=("Segoe UI", 8, "bold"),
                 fg=FG_DIM, bg=PANEL).pack(anchor="w", padx=14, pady=(0, 6))

        self._stat_commands = self._make_stat_row(side, "Commands")
        self._stat_words    = self._make_stat_row(side, "Words heard")
        self._stat_errors   = self._make_stat_row(side, "Errors")
        self._stat_uptime   = self._make_stat_row(side, "Uptime")

    def _make_stat_row(self, parent, label):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=14, pady=2)
        tk.Label(row, text=label, font=FONT_SMALL, fg=FG_DIM,
                 bg=PANEL).pack(side="left")
        val = tk.StringVar(value="0")
        tk.Label(row, textvariable=val, font=("Segoe UI", 9, "bold"),
                 fg=FG, bg=PANEL).pack(side="right")
        return val

    # — Log panel ——————————————————————————————
    def _build_log_panel(self, parent):
        right = tk.Frame(parent, bg=BG)
        right.pack(side="right", fill="both", expand=True)

        # Tab strip — Log / Commands
        self._notebook = ttk.Notebook(right)
        self._notebook.pack(fill="both", expand=True)

        style = ttk.Style()
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab",
            font=FONT_BODY, padding=(12, 6),
            background=PANEL, foreground=FG_DIM)
        style.map("TNotebook.Tab",
            background=[("selected", BG)],
            foreground=[("selected", FG)])

        # Tab 1 — Event log
        log_tab = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(log_tab, text="  Event Log  ")

        # Search bar
        search_row = tk.Frame(log_tab, bg=BG)
        search_row.pack(fill="x", pady=(6, 4))

        tk.Label(search_row, text="Filter:", font=FONT_SMALL,
                 fg=FG_DIM, bg=BG).pack(side="left", padx=(2, 4))

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        search_entry = tk.Entry(search_row, textvariable=self._search_var,
                                font=FONT_MONO, bg=PANEL, fg=FG,
                                insertbackground=FG, relief="flat",
                                highlightthickness=1,
                                highlightbackground=BORDER,
                                highlightcolor=ACCENT)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))

        ttk.Button(search_row, text="✕", style="EAR.TButton",
                   command=self._clear_filter).pack(side="left")

        self.log_text = scrolledtext.ScrolledText(
            log_tab,
            font=FONT_MONO,
            bg="#11111b",
            fg=FG,
            insertbackground=FG,
            wrap="word",
            state="disabled",
            relief="flat",
            padx=8, pady=6
        )
        self.log_text.pack(fill="both", expand=True)

        # Tab 2 — Command history
        hist_tab = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(hist_tab, text="  Command History  ")

        cols = ("Time", "Trigger", "Type")
        self._hist_tree = ttk.Treeview(hist_tab, columns=cols, show="headings",
                                       selectmode="browse")
        style.configure("Treeview",
            background="#11111b", foreground=FG,
            fieldbackground="#11111b", rowheight=26,
            font=FONT_BODY, borderwidth=0)
        style.configure("Treeview.Heading",
            background=PANEL, foreground=FG_DIM,
            font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview",
            background=[("selected", BORDER)],
            foreground=[("selected", FG)])

        for col, w in zip(cols, (80, 320, 120)):
            self._hist_tree.heading(col, text=col)
            self._hist_tree.column(col, width=w, anchor="w")

        vsb = ttk.Scrollbar(hist_tab, orient="vertical",
                             command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._hist_tree.pack(fill="both", expand=True)

        # ── Last command footer ────────────────
        footer = tk.Frame(right, bg=PANEL, height=36)
        footer.pack(fill="x", pady=(6, 0))
        footer.pack_propagate(False)

        tk.Label(footer, text="Last command:", font=FONT_SMALL,
                 fg=FG_DIM, bg=PANEL).pack(side="left", padx=12, pady=8)

        self._last_cmd_var = tk.StringVar(value="—")
        tk.Label(footer, textvariable=self._last_cmd_var,
                 font=("Segoe UI", 10, "bold"),
                 fg=MAUVE, bg=PANEL).pack(side="left", padx=4)

    # — Status bar ————————————————————————————
    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=PANEL, height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self._sb_var = tk.StringVar(value="Ready.")
        tk.Label(bar, textvariable=self._sb_var,
                 font=FONT_SMALL, fg=FG_DIM, bg=PANEL).pack(side="left", padx=12)

        self._keywords_count_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._keywords_count_var,
                 font=FONT_SMALL, fg=FG_DIM, bg=PANEL).pack(side="right", padx=12)

        self._refresh_keyword_count()

    # ──────────────────────────────────────────
    # Callbacks
    # ──────────────────────────────────────────
    def _connect_callbacks(self):
        self.recognizer.on_command_detected = self._cb_command
        self.recognizer.on_audio_playing    = self._cb_audio_playing
        self.recognizer.on_error            = self._cb_error
        self.recognizer.on_listening_start  = self._cb_listen_start
        self.recognizer.on_listening_stop   = self._cb_listen_stop
        self.recognizer.on_word_heard       = self._cb_word_heard

    def _cb_word_heard(self, text):
        self.message_queue.put(("word", text))

    def _cb_command(self, cmd, audio_file=None, action_info=None):
        self.message_queue.put(("command", cmd, audio_file, action_info))

    def _cb_audio_playing(self, audio_file):
        self.message_queue.put(("audio_play", audio_file))

    def _cb_error(self, msg):
        self.message_queue.put(("error", msg))

    def _cb_listen_start(self):
        self.message_queue.put(("listen_start", None))

    def _cb_listen_stop(self):
        self.message_queue.put(("listen_stop", None))

    # ──────────────────────────────────────────
    # Queue processor
    # ──────────────────────────────────────────
    def check_queue(self):
        try:
            while True:
                item = self.message_queue.get_nowait()
                msg_type, *data = item

                if msg_type == "word":
                    self.word_count += 1
                    self._stat_words.set(str(self.word_count))
                    self._log("HEARD", data[0], color=GOLD)

                elif msg_type == "command":
                    cmd, audio_file, action_info = data
                    self.command_count += 1
                    self._stat_commands.set(str(self.command_count))
                    self._last_cmd_var.set(f'"{cmd}"')

                    if action_info:
                        kind = "File" if action_info.get("type") == "fichier" else "App"
                        self._log("CMD", f"[{kind}] {cmd}", color=MAUVE)
                        self._hist_add(cmd, kind)
                    elif audio_file:
                        self._log("CMD", f"[Audio] {cmd}", color=MAUVE)
                        self._hist_add(cmd, "Audio")
                    else:
                        self._log("CMD", cmd, color=MAUVE)
                        self._hist_add(cmd, "—")

                elif msg_type == "audio_play":
                    fname = os.path.basename(data[0])
                    self._log("PLAY", fname, color=ACCENT)

                elif msg_type == "error":
                    self.error_count += 1
                    self._stat_errors.set(str(self.error_count))
                    self._log("ERR", data[0], color=ERROR)

                elif msg_type == "listen_start":
                    self._set_status("Listening", SUCCESS)
                    self._log("SYS", "Microphone active", color=SUCCESS)

                elif msg_type == "listen_stop":
                    self._set_status("Idle", FG_DIM)
                    self._log("SYS", "Microphone stopped", color=FG_DIM)

                self.message_queue.task_done()

        except Exception:
            pass

        self.root.after(80, self.check_queue)

    # ──────────────────────────────────────────
    # Log helpers
    # ──────────────────────────────────────────
    def _log(self, tag: str, message: str, color: str = FG):
        """Append a coloured line; prune oldest lines when cap is reached."""
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {tag:<6}  {message}\n"

        self.log_text.configure(state="normal")

        # Log rotation — remove oldest line when over cap
        max_lines = getattr(self.recognizer, "log_max_lines", 500)
        current   = int(self.log_text.index("end-1c").split(".")[0])
        if current > max_lines:
            self.log_text.delete("1.0", "2.0")

        start = self.log_text.index("end-1c")
        self.log_text.insert(tk.END, line)
        end   = self.log_text.index("end-1c")

        tag_name = f"col_{color.replace('#', '')}"
        self.log_text.tag_configure(tag_name, foreground=color)
        self.log_text.tag_add(tag_name, start, end)

        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        self._sb_var.set(message[:80])

    def _apply_filter(self):
        """Highlight lines matching the search string."""
        self.log_text.tag_remove("highlight", "1.0", tk.END)
        query = self._search_var.get().strip().lower()
        if not query:
            return
        self.log_text.tag_configure("highlight", background="#45475a")
        start = "1.0"
        while True:
            pos = self.log_text.search(query, start, nocase=True, stopindex=tk.END)
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            self.log_text.tag_add("highlight", pos, end)
            start = end

    def _clear_filter(self):
        self._search_var.set("")
        self.log_text.tag_remove("highlight", "1.0", tk.END)

    def _hist_add(self, cmd: str, kind: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._hist_tree.insert("", 0, values=(ts, cmd, kind))

    # ──────────────────────────────────────────
    # Status indicator
    # ──────────────────────────────────────────
    def _set_status(self, text: str, color: str):
        self._status_dot.config(fg=color)
        self._status_text.config(text=text, fg=color)

    # ──────────────────────────────────────────
    # Uptime ticker
    # ──────────────────────────────────────────
    def _tick_uptime(self):
        delta = datetime.now() - self.start_time
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m, s   = divmod(rem, 60)
        self._stat_uptime.set(f"{h:02d}:{m:02d}:{s:02d}")
        self.root.after(1000, self._tick_uptime)

    # ──────────────────────────────────────────
    # Button actions
    # ──────────────────────────────────────────
    def toggle_listening(self):
        if not self.recognizer.is_listening:
            self.start_listening()
        else:
            self.stop_listening()

    def start_listening(self):
        self.recognizer._start_thread()
        self.listen_btn.configure(text="■  Stop Listening", style="Danger.TButton")
        self._set_status("Listening", SUCCESS)
        self._log("SYS", "Starting microphone…", color=ACCENT)

    def stop_listening(self):
        self.recognizer.is_listening = False
        self.listen_btn.configure(text="▶  Start Listening", style="Primary.TButton")
        self._set_status("Idle", FG_DIM)
        self._log("SYS", "Microphone stopped.", color=FG_DIM)

    def calibrate_mic(self):
        self._log("SYS", "Calibrating microphone…", color=ACCENT)
        threading.Thread(target=self.recognizer.calibrer_micro,
                         daemon=True).start()

    def test_audio(self):
        test_sound = "sounds/thx.mp3"
        if os.path.exists(test_sound):
            self._log("TEST", "Playing test sound…", color=ACCENT)
            pygame.mixer.music.load(test_sound)
            pygame.mixer.music.play()
        else:
            self._log("TEST", "Test sound not found (sounds/thx.mp3)", color=WARN)

    def reload_keywords(self):
        self.recognizer.reload_keywords()
        self._refresh_keyword_count()
        self._log("SYS", f"keywords.txt reloaded — {len(self.recognizer.commands)} commands", color=ACCENT)

    def reload_actions(self):
        self.recognizer.reload_actions()
        n = len(self.recognizer.system_actions)
        self._log("SYS", f"actions.ini reloaded — {n} actions", color=ACCENT)

    def reload_config(self):
        self.recognizer.reload_config()
        self._log("SYS", "config.ini reloaded.", color=ACCENT)
        self._refresh_keyword_count()

    def measure_threshold(self):
        self._log("SYS", "Measuring ambient noise threshold…", color=ACCENT)
        threading.Thread(target=self.recognizer.measure_threshold,
                         daemon=True).start()

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self._log("SYS", "Log cleared.", color=FG_DIM)

    def _refresh_keyword_count(self):
        n       = len(getattr(self.recognizer, "commands", {}))
        backend = getattr(self.recognizer, "backend", "google").upper()
        self._keywords_count_var.set(f"{backend}  |  {n} keywords")

    # ──────────────────────────────────────────
    # Run
    # ──────────────────────────────────────────
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.eval("tk::PlaceWindow . center")
        self.root.mainloop()

    def _on_close(self):
        if self.recognizer.is_listening:
            self.stop_listening()
            self.root.after(400, self.root.destroy)
        else:
            self.root.destroy()