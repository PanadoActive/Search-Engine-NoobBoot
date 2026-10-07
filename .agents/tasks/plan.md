# Implementation Plan

## File: `index.py`

---

- [ ] 1. Add new instance attributes and refactor prefs into `_load_prefs` / `_save_prefs`.

  **What:** In `__init__`, replace the inline 6-line prefs read block (lines ~178–186 in current code)
  with a call to `self._load_prefs()`. Add all new state attributes to `__init__` in the same
  block where existing ones (`self.q`, `self._seq`, etc.) are initialised — before any widgets are built.

  New attributes to add in `__init__`, right after `self.catalog = searchlib.load_catalog()`:
  ```python
  self._folder_filter: str | None = None   # set by _load_prefs
  self._history: list[str] = []            # set by _load_prefs
  self._current_query: str = ""            # updated in start()
  self._folder_buttons: dict[str, ctk.CTkButton] = {}  # keyed by relative folder path
  ```

  **New method `_load_prefs()`** — reads PREFS_FILE once at startup, sets three attributes:
  ```python
  def _load_prefs(self):
      try:
          with open(PREFS_FILE, encoding="utf-8") as f:
              p = json.load(f)
      except Exception:
          p = {}
      self.is_dark        = bool(p.get("dark_mode", False))
      self._history       = list(p.get("search_history", []))[:20]
      self._folder_filter = p.get("folder_filter") or None
  ```
  Call `self._load_prefs()` at the very start of `__init__`, before the `top` frame is built.
  Then immediately apply the loaded theme:
  ```python
  ctk.set_appearance_mode("Dark" if self.is_dark else "Light")
  ```

  **New method `_save_prefs()`** — writes all three keys atomically:
  ```python
  def _save_prefs(self):
      try:
          with open(PREFS_FILE, "w", encoding="utf-8") as f:
              json.dump({
                  "dark_mode":      self.is_dark,
                  "search_history": self._history[:20],
                  "folder_filter":  self._folder_filter,
              }, f)
      except Exception:
          pass
  ```

  **Modify `toggle_theme()`** — replace its inline json.dump block with a call to `self._save_prefs()`:
  ```python
  def toggle_theme(self):
      self.is_dark = not self.is_dark
      ctk.set_appearance_mode("Dark" if self.is_dark else "Light")
      self.theme_btn.configure(text="Light mode" if self.is_dark else "Dark mode")
      self._save_prefs()
  ```

  Files: `index.py`
  Verify: `python -m unittest discover -s tests -v` — all existing tests still pass (no GUI changes yet).

---

- [ ] 2. Restructure the layout in `__init__`: add history frame and horizontal split.

  **What:** Change the pack order after the `top` bar is built. The new pack order replaces the
  current single-line `self.tabs.pack(...)` with three items: history frame, a split container,
  and the sidebar + tabs inside that container.

  **Step A — history frame** (inserted between `top` pack and `progress_bar` pack):
  ```python
  # History dropdown (hidden by default; shown on entry FocusIn)
  self.history_frame = ctk.CTkScrollableFrame(root, height=150, fg_color=("gray95", "gray20"))
  self.history_frame.pack(fill="x", padx=12, pady=(0, 0))
  self.history_frame.pack_forget()   # hidden initially
  ```

  **Step B — keep progress_bar and status packs unchanged** (no change to those two lines).

  **Step C — replace `self.tabs.pack(...)` with a horizontal split container**:
  ```python
  # Horizontal split: sidebar (left) + tabs (right)
  self._split = ctk.CTkFrame(root, fg_color="transparent")
  self._split.pack(fill="both", expand=True, padx=12, pady=(4, 12))

  self._sidebar = ctk.CTkScrollableFrame(self._split, width=200, label_text="Folders")
  self._sidebar.pack(side="left", fill="y", padx=(0, 4))

  self.tabs = ctk.CTkTabview(self._split)
  self.tabs.pack(side="left", fill="both", expand=True)
  ```

  Note: `self.tabs` is still named `self.tabs`; all downstream code (`self.tabs.add(...)`,
  `self.tabs.set(...)`) is unchanged.

  **Step D — bind focus events on `self.entry`** (add immediately after `self.entry` is created):
  ```python
  self.entry.bind("<FocusIn>",  lambda e: self._show_history())
  self.entry.bind("<FocusOut>", lambda e: self.root.after(200, self._hide_history))
  ```

  Files: `index.py`
  Verify: `python -m unittest discover -s tests -v` — all tests still pass (tests don't instantiate the GUI).

---

- [ ] 3. Add `_build_sidebar()` method and call it from `__init__` and `reload()`.

  **What:** Implement the folder tree in the left sidebar.

  ```python
  def _build_sidebar(self):
      """Rebuild the folder list in the left sidebar."""
      clear(self._sidebar)
      self._folder_buttons = {}

      # "All folders" button at the top
      btn_all = ctk.CTkButton(
          self._sidebar, text="All folders", anchor="w",
          fg_color=("gray75", "gray35") if self._folder_filter is None else "transparent",
          command=lambda: self._set_folder(None),
      )
      btn_all.pack(fill="x", padx=4, pady=(4, 2))

      # Walk INFORMATION_DIR for subdirectories
      subdirs = []
      for dirpath, dirnames, _ in os.walk(INFORMATION_DIR):
          dirnames[:] = [d for d in sorted(dirnames) if not d.startswith(".")]
          rel = Path(dirpath).relative_to(INFORMATION_DIR)
          if rel == Path("."):
              continue   # skip root itself
          depth = len(rel.parts)
          subdirs.append((str(rel), depth))

      if not subdirs:
          label(self._sidebar, "No subfolders yet.", 11, MUTED).pack(anchor="w", padx=8, pady=4)
          return

      for rel_str, depth in subdirs:
          indent = "  " * depth
          is_selected = self._folder_filter == rel_str
          btn = ctk.CTkButton(
              self._sidebar,
              text=indent + Path(rel_str).name,
              anchor="w",
              fg_color=("gray75", "gray35") if is_selected else "transparent",
              command=lambda r=rel_str: self._set_folder(r),
          )
          btn.pack(fill="x", padx=4, pady=1)
          self._folder_buttons[rel_str] = btn
  ```

  **Add `_set_folder()` helper**:
  ```python
  def _set_folder(self, rel: str | None):
      self._folder_filter = rel
      self._save_prefs()
      self._build_sidebar()   # refresh highlight
      self.start()
  ```

  **Add folder filtering in `run()`** — after `results = self._apply_date_filter(...)` and before
  `results = self._apply_sort(...)`:
  ```python
  if self._folder_filter:
      results = [r for r in results
                 if r.get("relative_path", "").startswith(self._folder_filter)]
  ```

  **Modify `reload()`** — add `self._build_sidebar()` call:
  ```python
  def reload(self):
      self.catalog = searchlib.load_catalog()
      self._refresh_types()
      self._build_sidebar()   # <-- add this line
      self.start()
  ```

  **Call from `__init__`** — after `self.frames` and `self.texts` are fully populated (at the end of
  the widget-building section, just before `root.protocol(...)` and `self.poll()`):
  ```python
  self._build_sidebar()
  ```

  Files: `index.py`
  Verify: `python -m unittest discover -s tests -v` — all tests pass.

---

- [ ] 4. Add `_show_history()`, `_hide_history()`, and `_build_history_frame()` methods; update `start()` to maintain history.

  **What:** Implement the search history dropdown.

  **`_build_history_frame()`** — rebuild the contents of `self.history_frame`:
  ```python
  def _build_history_frame(self):
      clear(self.history_frame)
      if not self._history:
          return
      for q in self._history:
          def _pick(query=q):
              self.entry.delete(0, "end")
              self.entry.insert(0, query)
              self._hide_history()
              self.start()
          btn = ctk.CTkButton(
              self.history_frame, text=q, anchor="w",
              fg_color="transparent", hover_color=("gray80", "gray30"),
              command=_pick,
          )
          btn.pack(fill="x", padx=4, pady=1)
      # Clear history button at the bottom
      ctk.CTkButton(
          self.history_frame, text="✕  Clear history", anchor="w",
          fg_color="transparent", text_color=MUTED,
          command=self._clear_history,
      ).pack(fill="x", padx=4, pady=(4, 2))
  ```

  **`_show_history()`**:
  ```python
  def _show_history(self):
      if not self._history:
          return
      self._build_history_frame()
      self.history_frame.pack(fill="x", padx=12, pady=(0, 0))
      # Re-insert below top bar: lift history_frame above progress_bar
      self.history_frame.lift()
  ```

  **`_hide_history()`**:
  ```python
  def _hide_history(self):
      self.history_frame.pack_forget()
  ```

  **`_clear_history()`**:
  ```python
  def _clear_history(self):
      self._history = []
      self._save_prefs()
      self._hide_history()
  ```

  **Modify `start()`** — add two lines right after `kw = self.entry.get().strip()`:
  ```python
  self._current_query = kw
  if kw and (not self._history or self._history[0] != kw):
      self._history.insert(0, kw)
      self._history = self._history[:20]
      self._save_prefs()
  ```

  Files: `index.py`
  Verify: `python -m unittest discover -s tests -v` — all tests pass.

---

- [ ] 5. Restructure the Documents tab and add `_open_viewer()` and `_close_viewer()`.

  **What:** Split the Documents tab into a top scrollable results area and a bottom viewer pane.

  **Step A — change how the Documents tab frame is created** in `__init__`.

  Current code for the three tabs (`Documents`, `By Type`, `Keywords`) is a single loop:
  ```python
  for name in ("Documents", "By Type", "Keywords"):
      f = ctk.CTkScrollableFrame(self.tabs.add(name), fg_color="transparent")
      f.pack(fill="both", expand=True)
      self.frames[name] = f
  ```

  Replace with:
  ```python
  # Documents tab — vertical split: results list (top) + viewer pane (bottom)
  doc_tab = self.tabs.add("Documents")
  self.frames["Documents"] = ctk.CTkScrollableFrame(doc_tab, fg_color="transparent")
  self.frames["Documents"].pack(fill="both", expand=True)

  # Viewer pane (hidden initially)
  self.viewer_frame = ctk.CTkFrame(doc_tab, fg_color=("gray90", "gray17"))
  # Do NOT pack it here — it starts hidden.

  # Viewer header bar
  viewer_header = ctk.CTkFrame(self.viewer_frame, fg_color="transparent")
  viewer_header.pack(fill="x", padx=4, pady=(4, 0))
  self.viewer_title = ctk.CTkLabel(viewer_header, text="", anchor="w",
                                   font=ctk.CTkFont(size=13, weight="bold"))
  self.viewer_title.pack(side="left", fill="x", expand=True)
  ctk.CTkButton(viewer_header, text="✕", width=28, height=28,
                command=self._close_viewer).pack(side="right")

  # Viewer textbox
  self.viewer_box = ctk.CTkTextbox(self.viewer_frame, wrap="word",
                                   font=ctk.CTkFont(family="Consolas", size=12))
  self.viewer_box.pack(fill="both", expand=True, padx=4, pady=(2, 4))
  self.viewer_box.configure(state="disabled")

  # By Type and Keywords (unchanged)
  for name in ("By Type", "Keywords"):
      f = ctk.CTkScrollableFrame(self.tabs.add(name), fg_color="transparent")
      f.pack(fill="both", expand=True)
      self.frames[name] = f
  ```

  **Step B — add `_open_viewer(row)`**:
  ```python
  def _open_viewer(self, row):
      path = resolve_path(row)
      if not path.exists():
          self.status.configure(text=f"File not found: {path}")
          return
      try:
          text = path.read_text(encoding="utf-8", errors="replace")[:50_000]
      except Exception as exc:
          self.status.configure(text=f"Could not read file: {exc}")
          return

      self.viewer_box.configure(state="normal")
      self.viewer_box.delete("1.0", "end")
      self.viewer_box.insert("end", text)

      # Highlight current query terms
      self.viewer_box.tag_config("highlight", background="#fff176", foreground="#000000")
      first_index = None
      if self._current_query:
          terms = [w for w in re.findall(r"\w+", self._current_query) if len(w) >= 2]
          for term in terms:
              for m in re.finditer(re.escape(term), text, re.IGNORECASE):
                  start = f"1.0 + {m.start()} chars"
                  end   = f"1.0 + {m.end()} chars"
                  self.viewer_box.tag_add("highlight", start, end)
                  if first_index is None:
                      first_index = start

      self.viewer_box.configure(state="disabled")
      self.viewer_title.configure(text=row.get("file_name", ""))

      # Show the pane at ~35% of the tab height
      self.viewer_frame.pack(fill="x", padx=0, pady=(4, 0), ipady=0,
                             in_=self.frames["Documents"].master)
      # Use place geometry to give it roughly 35% height in the parent tab
      self.viewer_frame.pack(fill="x", side="bottom")

      if first_index:
          self.viewer_box.see(first_index)
  ```

  > Implementation note on the split geometry: Because CustomTkinter's `CTkScrollableFrame`
  > fills the tab with `expand=True`, adding a `side="bottom"` frame afterwards will naturally
  > claim the bottom portion. No explicit `place()` or `PanedWindow` is needed — Tkinter pack
  > handles this correctly as long as the results frame is packed first with `expand=True` and
  > the viewer frame is packed after with `side="bottom"` (no expand).

  **Step C — add `_close_viewer()`**:
  ```python
  def _close_viewer(self):
      self.viewer_frame.pack_forget()
  ```

  **Step D — modify `_doc_card()` to open the viewer for `.txt` / `.md` files**:

  In the existing `_doc_card()` method, locate the line:
  ```python
  clickable(head, prefix + r.get("file_name", "(unnamed)"), lambda row=r: self._open(row)).pack(side="left")
  ```
  Replace with:
  ```python
  ext = Path(r.get("file_name", "")).suffix.lower()
  if ext in (".txt", ".md"):
      title_cb = lambda row=r: self._open_viewer(row)
  else:
      title_cb = lambda row=r: self._open(row)
  clickable(head, prefix + r.get("file_name", "(unnamed)"), title_cb).pack(side="left")
  ```

  Files: `index.py`
  Verify: `python -m unittest discover -s tests -v` — all 22 tests pass (1 skipped is acceptable).

---

## Order-of-operations notes for the implementer

The pack order inside `__init__` after all changes must be exactly:

1. `top.pack(fill="x", padx=12, pady=(12, 4))` — top bar (no change)
2. `self.history_frame.pack(fill="x", padx=12)` then immediately `self.history_frame.pack_forget()` — hidden initially
3. `self.progress_bar.pack(...)` then immediately `self.progress_bar.pack_forget()` — unchanged
4. `self.status.pack(fill="x", padx=16)` — unchanged
5. `self._split.pack(fill="both", expand=True, padx=12, pady=(4, 12))` — new split container
   - `self._sidebar.pack(side="left", fill="y", padx=(0, 4))` inside `_split`
   - `self.tabs.pack(side="left", fill="both", expand=True)` inside `_split`

Inside the Documents tab (child of `self.tabs.tab("Documents")`):
1. `self.frames["Documents"].pack(fill="both", expand=True)` — results list (expands to fill)
2. `self.viewer_frame` — **not packed** at init time (hidden); `pack(fill="x", side="bottom")` only when `_open_viewer()` is called

### Key constraints

- `self.tabs` must be a child of `self._split`, not of `root` directly. Every other reference to `self.tabs` in existing code (`self.tabs.add(...)`, `self.tabs.set(...)`) is unaffected because the attribute name is preserved.
- The `history_frame` must be packed into `root` (not `top`) so it appears as a full-width dropdown below the search bar row. It must be packed (then forgotten) before `progress_bar` so that when shown, it inserts visually at the correct position.
- `_build_sidebar()` must be called after `self._split` and `self._sidebar` are created, and after `self.frames`/`self.texts` are populated — specifically, after the tab-building loop completes and before `root.protocol(...)`.
- `self._current_query` must be set to `""` in `__init__` before any search runs (so the viewer highlights nothing on a cold open).
- `_load_prefs()` must be called before `ctk.set_appearance_mode(...)` and before any widget that depends on `self.is_dark`.

### What the tests cover (and don't)

The test suite (`tests/test_core.py`) covers `build_simple`, `build_advanced`, `ingest`, `searchlib`, and `extract_data`. It does **not** instantiate the GUI. All 22 tests pass without running `index.py`, so every plan item can be verified by running:

```
python -m unittest discover -s tests -v
```

from `c:\Users\user\Downloads\Search-Engine-NoobBoot-improved\Search-Engine-NoobBoot-improved`.
