"""Thought dump: save a thought fast, sort it later, find it again.

  dump                 open the window
  dump "text"          save a thought (--task, --idea or --mind to label it)
  dump -f words        search (add --expand for related words)
"""
import os
import re
import sqlite3
import sys
import threading
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, font as tkfont
except ImportError:
    tk = None

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "thoughts.db")
BACKUP_DIR = os.path.join(HERE, "backups")
ARCHIVE_DAYS = 30
MODEL_ALIAS = "qwen2.5-1.5b"

LABELS = {"task": "Task", "idea": "Idea", "mind": "On my mind", "none": "Unlabelled"}
FILLER = set("""a an and are about as at be but by can could did do does for from how i if in is it
me my of on or should so than that the then there this to was we what when where which who why will
with would you your""".split())
EMPTY = {
    "tasks": "No open tasks. Save one with the Task label.",
    "idea": "Ideas you label show up here.",
    "mind": "Anything on your mind shows up here, kept out of your task list.",
    "none": "Nothing waiting for a label.",
    "archive": "Archived items wait here for 30 days.",
}
HELP = __doc__

EXPAND_PROMPT = """List up to 8 words related to the search words, as one comma-separated line. Lowercase single words only. No explanations.

Search: tired and sleepy
Related: exhausted, rest, nap, fatigue, bed, energy, sleep, drowsy

Search: buy groceries
Related: shopping, market, food, store, list, vegetables, supplies, errand

Search: {query}
Related:"""


# ---------- database ----------

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cols = {r["name"] for r in con.execute("PRAGMA table_info(thoughts)")}
    if "state" not in cols:
        sys.exit("Database not migrated yet. Run migrate.py first.")
    return con


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def purge(con):
    cur = con.execute(
        "DELETE FROM thoughts WHERE state='archived' "
        "AND julianday('now','localtime') - julianday(state_changed) >= ?", (ARCHIVE_DAYS,))
    con.commit()
    return cur.rowcount


def add(con, text, label="none"):
    con.execute(
        "INSERT INTO thoughts (text, created, label, status, state, state_changed) VALUES (?,?,?,?,?,?)",
        (text, stamp(), label, "", "open", stamp()))
    con.commit()


def set_state(con, ids, state):
    con.executemany("UPDATE thoughts SET state=?, state_changed=? WHERE id=?",
                    [(state, stamp(), i) for i in ids])
    con.commit()


def archive_done(con):
    cur = con.execute("UPDATE thoughts SET state='archived', state_changed=? "
                      "WHERE label='task' AND state='done'", (stamp(),))
    con.commit()
    return cur.rowcount


def set_label(con, i, label):
    con.execute("UPDATE thoughts SET label=? WHERE id=?", (label, i))
    con.commit()


def fetch(con, key):
    if key == "tasks":
        return con.execute("SELECT * FROM thoughts WHERE label='task' AND state IN ('open','done') "
                           "ORDER BY (state='done'), id").fetchall()
    if key == "archive":
        return con.execute(
            "SELECT *, CAST(julianday('now','localtime') - julianday(state_changed) AS INTEGER) AS age "
            "FROM thoughts WHERE state='archived' ORDER BY state_changed DESC").fetchall()
    return con.execute("SELECT * FROM thoughts WHERE label=? AND state='open' ORDER BY id DESC",
                       (key,)).fetchall()


# ---------- search ----------

def keywords(text):
    return [w for w in re.findall(r"[A-Za-z0-9]+", text.lower()) if w not in FILLER]


def search(con, words, exclude=()):
    if not words:
        return []
    q = " OR ".join(f'"{w}"*' for w in words)
    rows = con.execute(
        "SELECT thoughts.* FROM thoughts_fts JOIN thoughts ON thoughts.id = thoughts_fts.rowid "
        "WHERE thoughts_fts MATCH ? ORDER BY bm25(thoughts_fts)", (q,)).fetchall()
    return [r for r in rows if r["id"] not in exclude]


def expand_words(words):
    """Ask the local model for words related to `words`.

    Return a list of words, or one line of words.
    """
    query = " ".join(words)
    print("asking the model for related words (a few seconds)...", flush=True)

    try:
        from foundry_local_sdk import Configuration, FoundryLocalManager

        FoundryLocalManager.initialize(Configuration(app_name="thought_dump"))
        model = FoundryLocalManager.instance.catalog.get_model(MODEL_ALIAS)
        if model is None:
            print(f"model '{MODEL_ALIAS}' not found in the SDK catalog")
            return []
        model.download()
        model.load()
    except Exception as e:
        print(f"model unavailable: {e}")
        return []

    try:
        client = model.get_chat_client()
        reply = (
            client.complete_chat(
                [{"role": "user", "content": EXPAND_PROMPT.format(query=query)}]
            )
            .choices[0]
            .message.content
        )
    except Exception as e:
        print(f"model failed: {e}")
        return []
    finally:
        model.unload()

    return reply


def related(words):
    raw = expand_words(words)
    if isinstance(raw, str):
        raw = re.findall(r"[A-Za-z0-9]+", raw)
    out = []
    for w in raw:
        w = str(w).lower().strip()
        if len(w) >= 3 and w.isalnum() and w not in FILLER and w not in words and w not in out:
            out.append(w)
    return out[:8]


def tag(r):
    return "Archive" if r["state"] == "archived" else LABELS.get(r["label"], "Unlabelled")


# ---------- window ----------

if tk:
    class ScrollList(tk.Frame):
        def __init__(self, parent, bg):
            super().__init__(parent, bg=bg)
            self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
            bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.inner = tk.Frame(self.canvas, bg=bg)
            self.inner.bind("<Configure>",
                            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
            self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
            self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
            self.canvas.configure(yscrollcommand=bar.set)
            self.canvas.pack(side="left", fill="both", expand=True)
            bar.pack(side="right", fill="y")

        def clear(self):
            for w in self.inner.winfo_children():
                w.destroy()

    class App:
        TABS = [("tasks", "Tasks"), ("idea", "Ideas"), ("mind", "On my mind"),
                ("none", "Unlabelled"), ("archive", "Archive"), ("search", "Search")]

        def __init__(self, root):
            self.root = root
            root.title("Thought dump")
            root.geometry("820x620")
            root.minsize(560, 420)
            root.protocol("WM_DELETE_WINDOW", self.close)
            
            # Visual hierarchy color tokens
            self.bg_color = "#f4f5f7"
            self.card_bg = "#ffffff"
            self.text_main = "#1e293b"
            self.accent = "#3b82f6"
            
            root.configure(bg=self.bg_color)
            style = ttk.Style()
            style.theme_use("clam")
            style.configure(".", background=self.bg_color, foreground=self.text_main, font=("Segoe UI", 10))
            style.configure("TNotebook", background=self.bg_color, borderwidth=0)
            style.configure("TNotebook.Tab", padding=[12, 8], font=("Segoe UI", 10, "bold"))
            style.configure("Card.TFrame", background=self.card_bg, relief="flat")
            style.configure("TButton", padding=6, relief="flat", background="#e2e8f0")
            style.configure("Primary.TButton", background=self.accent, foreground="#ffffff")

            self.con = connect()
            purged = purge(self.con)
            self.font = tkfont.nametofont("TkDefaultFont")
            self.done_font = self.font.copy()
            self.done_font.configure(overstrike=True)
            
            self.vars, self.lists, self.allvar, self.count_lbl, self.act_btn = {}, {}, {}, {}, {}
            self.search_id = 0

            top = ttk.Frame(root, padding=(16, 16, 16, 8))
            top.pack(fill="x")
            self.entry = ttk.Entry(top, font=("Segoe UI", 11))
            self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
            self.entry.bind("<Return>", lambda e: self.save())
            
            self.picks = {k: tk.BooleanVar(value=False) for k in ("task", "idea", "mind")}
            for k in ("task", "idea", "mind"):
                ttk.Checkbutton(top, text=LABELS[k], variable=self.picks[k],
                                command=lambda k=k: self.pick(k)).pack(side="left", padx=(4, 0))
            ttk.Button(top, text="Save", style="Primary.TButton", command=self.save).pack(side="left", padx=(10, 0))
            
            self.err = ttk.Label(root, foreground="#dc2626", font=("Segoe UI", 9, "bold"))
            self.err.pack(anchor="w", padx=18)

            foot = ttk.Frame(root, padding=(16, 8))
            foot.pack(side="bottom", fill="x")
            self.status = ttk.Label(
                foot, text=f"Cleared {purged} item{'' if purged == 1 else 's'} older than {ARCHIVE_DAYS} days",
                font=("Segoe UI", 9), foreground="#64748b")
            self.status.pack(side="left")
            ttk.Button(foot, text="Back up", command=self.backup).pack(side="right")

            self.nb = ttk.Notebook(root)
            self.nb.pack(fill="both", expand=True, padx=16, pady=4)
            self.frames = {}
            for key, title in self.TABS:
                f = ttk.Frame(self.nb, padding=8)
                self.nb.add(f, text=title)
                self.frames[key] = f
            for key in ("tasks", "idea", "mind", "none", "archive"):
                self.build_header(key)
                self.lists[key] = ScrollList(self.frames[key], self.bg_color)
                self.lists[key].pack(fill="both", expand=True)
            self.build_search()
            root.bind_all("<MouseWheel>", self.on_wheel)
            self.refresh_all()
            self.entry.focus()

        # layout pieces
        def build_header(self, key):
            h = ttk.Frame(self.frames[key])
            h.pack(fill="x", pady=(0, 8))
            if key == "tasks":
                self.task_count = ttk.Label(h, font=("Segoe UI", 10, "bold"), foreground="#475569")
                self.task_count.pack(side="left")
                ttk.Button(h, text="Refresh Done", command=self.refresh_tasks).pack(side="right")
                return
            self.allvar[key] = tk.BooleanVar()
            tk.Checkbutton(h, variable=self.allvar[key], bg=self.bg_color, activebackground=self.bg_color,
                           command=lambda k=key: self.select_all(k)).pack(side="left")
            self.count_lbl[key] = ttk.Label(h, font=("Segoe UI", 9, "bold"), foreground="#475569")
            self.count_lbl[key].pack(side="left", padx=(6, 0))
            self.act_btn[key] = ttk.Button(h, text="Restore Selected" if key == "archive" else "Archive Selected",
                                           command=lambda k=key: self.act(k))
            self.act_btn[key].pack(side="right")

        def build_search(self):
            f = self.frames["search"]
            bar = ttk.Frame(f)
            bar.pack(fill="x", pady=(0, 8))
            self.q = ttk.Entry(bar, font=("Segoe UI", 11))
            self.q.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
            self.q.bind("<Return>", lambda e: self.run_search())
            self.expand_var = tk.BooleanVar()
            ttk.Checkbutton(bar, text="Also try related words (slower)",
                            variable=self.expand_var).pack(side="left", padx=4)
            ttk.Button(bar, text="Search", style="Primary.TButton", command=self.run_search).pack(side="left", padx=(8, 0))
            self.lists["search"] = ScrollList(f, self.bg_color)
            self.lists["search"].pack(fill="both", expand=True)

        # loading lists
        def refresh_all(self):
            for key in ("tasks", "idea", "mind", "none", "archive"):
                self.load(key)

        def load(self, key):
            lst = self.lists[key]
            lst.clear()
            rows = fetch(self.con, key)
            if key == "tasks":
                done = sum(1 for r in rows if r["state"] == "done")
                self.task_count.config(text=f"{len(rows) - done} open tasks, {done} completed")
            else:
                self.vars[key] = []
            if not rows:
                ttk.Label(lst.inner, text=EMPTY[key], foreground="#94a3b8", font=("Segoe UI", 10, "italic")).pack(anchor="w", pady=12, padx=4)
            for r in rows:
                card = tk.Frame(lst.inner, bg=self.card_bg, highlightbackground="#e2e8f0", highlightthickness=1)
                card.pack(fill="x", pady=3, ipady=4, ipadx=6)
                
                if key == "tasks":
                    var = tk.BooleanVar(value=(r["state"] == "done"))
                    opts = dict(text=r["text"], variable=var, bg=self.card_bg, activebackground=self.card_bg,
                                anchor="w", justify="left", wraplength=520, font=("Segoe UI", 10))
                    if r["state"] == "done":
                        opts.update(font=self.done_font, fg="#94a3b8")
                    opts["command"] = lambda i=r["id"]: self.toggle(i)
                    tk.Checkbutton(card, **opts).pack(side="left", fill="x", expand=True, padx=4)
                else:
                    var = tk.BooleanVar(value=False)
                    self.vars[key].append((r["id"], var))
                    opts = dict(text=r["text"], variable=var, bg=self.card_bg, activebackground=self.card_bg,
                                anchor="w", justify="left", wraplength=480, font=("Segoe UI", 10))
                    opts["command"] = lambda k=key: self.update_bar(k)
                    tk.Checkbutton(card, **opts).pack(side="left", fill="x", expand=True, padx=4)

                if key == "archive":
                    left = max(ARCHIVE_DAYS - r["age"], 0)
                    ttk.Label(card, foreground="#64748b", font=("Segoe UI", 9),
                              text=f"{LABELS[r['label']]}, clears in {left}d").pack(side="right", padx=8)
                if key == "none":
                    for k in ("mind", "idea", "task"):
                        ttk.Button(card, text=LABELS[k], width=9,
                                   command=lambda i=r["id"], k=k: self.sort(i, k)).pack(side="right", padx=2)
            if key != "tasks":
                self.update_bar(key)

        def update_bar(self, key):
            items = self.vars[key]
            n = sum(1 for _, v in items if v.get())
            verb = "restore" if key == "archive" else "archive"
            self.count_lbl[key].config(text=f"{n} selected" if n else f"Select items to {verb}")
            self.act_btn[key].config(state="normal" if n else "disabled")
            self.allvar[key].set(bool(items) and n == len(items))

        def select_all(self, key):
            val = self.allvar[key].get()
            for _, v in self.vars[key]:
                v.set(val)
            self.update_bar(key)

        # actions
        def say(self, msg):
            self.status.config(text=msg)

        def pick(self, key):
            if self.picks[key].get():
                for k, v in self.picks.items():
                    if k != key:
                        v.set(False)

        def save(self):
            text = self.entry.get().strip()
            if not text:
                self.err.config(text="Type a thought first")
                return
            self.err.config(text="")
            label = next((k for k, v in self.picks.items() if v.get()), "none")
            add(self.con, text, label)
            self.entry.delete(0, "end")
            for v in self.picks.values():
                v.set(False)
            self.say(f"Saved to {LABELS[label]}")
            self.refresh_all()

        def toggle(self, i):
            state = self.con.execute("SELECT state FROM thoughts WHERE id=?", (i,)).fetchone()["state"]
            set_state(self.con, [i], "open" if state == "done" else "done")
            self.load("tasks")

        def refresh_tasks(self):
            n = archive_done(self.con)
            self.say(f"Archived {n} done task{'' if n == 1 else 's'}" if n else "No done tasks to archive")
            self.refresh_all()

        def act(self, key):
            ids = [i for i, v in self.vars[key] if v.get()]
            if not ids:
                return
            if key == "archive":
                set_state(self.con, ids, "open")
                self.say(f"Restored {len(ids)} item{'' if len(ids) == 1 else 's'}")
            else:
                set_state(self.con, ids, "archived")
                self.say(f"Archived {len(ids)} item{'' if len(ids) == 1 else 's'}")
            self.refresh_all()

        def sort(self, i, label):
            set_label(self.con, i, label)
            self.say(f"Sorted into {LABELS[label]}")
            self.refresh_all()

        def backup(self):
            os.makedirs(BACKUP_DIR, exist_ok=True)
            folder = filedialog.askdirectory(initialdir=BACKUP_DIR, title="Choose where to save the backup")
            if not folder:
                self.say("Backup cancelled")
                return
            path = os.path.join(folder, f"thoughts_{datetime.now():%Y-%m-%d_%H%M}.db")
            dest = sqlite3.connect(path)
            try:
                self.con.backup(dest)
            finally:
                dest.close()
            self.say(f"Backup saved: {path}")

        # search
        def result(self, lst, text, color=None):
            lbl = ttk.Label(lst.inner, text=text, wraplength=640, justify="left", font=("Segoe UI", 10))
            if color:
                lbl.config(foreground=color)
            lbl.pack(anchor="w", pady=4, padx=6)
            return lbl

        def run_search(self):
            self.search_id += 1
            sid = self.search_id
            lst = self.lists["search"]
            lst.clear()
            words = keywords(self.q.get())
            if not words:
                self.result(lst, "Type a word to search for.", "#94a3b8")
                return
            rows = search(self.con, words)
            for r in rows:
                self.result(lst, f"[{tag(r)}] {r['text']}")
            if not rows:
                self.result(lst, "No matches. Try another word or turn on related words.", "#94a3b8")
            if not self.expand_var.get():
                return
            note = self.result(lst, "Looking for related words…", "#64748b")
            shown = {r["id"] for r in rows}

            def work():
                try:
                    extra = related(words)
                    c = connect()
                    hits = search(c, extra, exclude=shown) if extra else []
                    c.close()
                    msg, out = (f"Related: {', '.join(extra)}" if extra else "No related words found."), hits
                except Exception as e:
                    msg, out = f"Related words failed ({e}). The results above still stand.", []
                self.root.after(0, lambda: self.finish_related(sid, note, msg, out))

            threading.Thread(target=work, daemon=True).start()

        def finish_related(self, sid, note, msg, hits):
            if sid != self.search_id:
                return
            note.config(text=msg)
            for r in hits:
                self.result(self.lists["search"], f"[{tag(r)}] {r['text']}")

        def on_wheel(self, e):
            key = self.TABS[self.nb.index("current")][0]
            lst = self.lists.get(key)
            if lst:
                lst.canvas.yview_scroll(int(-e.delta / 120), "units")

        def close(self):
            self.con.close()
            self.root.destroy()


def run_gui():
    if tk is None:
        sys.exit("tkinter is missing from this Python install.")
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


# ---------- command line ----------

def cli_find(con, args):
    expand = "--expand" in args
    words = keywords(" ".join(a for a in args if a != "--expand"))
    if not words:
        print("Type some words to search for.")
        return
    rows = search(con, words)
    for r in rows:
        print(f"  [{tag(r)}] {r['text']}")
    if not rows:
        print("  No matches.")
    if expand:
        try:
            extra = related(words)
            hits = search(con, extra, exclude={r["id"] for r in rows}) if extra else []
            print("\nRelated:", ", ".join(extra) if extra else "none found")
            for r in hits:
                print(f"  [{tag(r)}] {r['text']}")
        except Exception as e:
            print(f"\nRelated words failed: {e}")


def main():
    args = sys.argv[1:]
    if not args:
        return run_gui()
    if args[0] in ("-h", "--help"):
        print(HELP)
        return
    con = connect()
    purged = purge(con)
    if purged:
        print(f"Cleared {purged} item(s) older than {ARCHIVE_DAYS} days.")
    if args[0] in ("-f", "--find"):
        return cli_find(con, args[1:])
    flags = {"--task": "task", "--idea": "idea", "--mind": "mind", "--worry": "mind"}
    label, words = "none", []
    for a in args:
        if a in flags:
            label = flags[a]
        elif a.startswith("-"):
            sys.exit(f"Unknown option {a}. Run dump --help.")
        else:
            words.append(a)
    text = " ".join(words).strip()
    if not text:
        sys.exit("Nothing to save. Put the thought in quotes.")
    add(con, text, label)
    print(f"Saved to {LABELS[label]}.")


if __name__ == "__main__":
    main()