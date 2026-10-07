# Three-feature addition: Folder Sidebar, Search History, Text Viewer — v2 review

This is a second-pass review. The prior pass raised four blocking issues; all four have been addressed in the current implementation. The change adds a folder/department browse sidebar, a search history dropdown, and a built-in text viewer pane to `index.py`, with a consolidated `_load_prefs`/`_save_prefs` layer backing all three features.

**Watch for:** One non-blocking defect remains: `_refresh_types()` contains two duplicate statement pairs (the `types = sorted(...)` + `type_menu.configure(...)` block is repeated verbatim). This is harmless but is dead code that should be removed.

**Verdict**: APPROVED

---

## High-level view

All four issues from the prior review are confirmed fixed. `_save_prefs()` now uses `tempfile.mkstemp` + `os.replace` for atomic writes, matching the pattern used in `ingest.py` for `data.csv`. The folder filter in `run()` normalises both the filter value and `relative_path` to forward slashes, and uses a `== norm_filter or startswith(prefix)` check that eliminates the prefix collision. `_open_viewer()` calls `viewer_box.see(first_index)` before `viewer_box.configure(state="disabled")`, fixing the silent no-op scroll. Path separator sensitivity is handled by normalising to forward slashes in both `_build_sidebar()` (where `rel_str` is built) and `_set_folder()` (where the stored filter value is normalised on write).

One pre-existing (not new) defect is present in `_refresh_types()`: the `types = sorted(...)` and `type_menu.configure(...)` lines appear twice, making the second pair a no-op. This has no behavioral effect.

---

<details>
<summary>Issues (1)</summary>

1. **Duplicate statements in `_refresh_types()`** — the `types = sorted(...)` + `type_menu.configure(values=...)` block appears twice in the method body. The second execution is a no-op and the code is harmless, but it should be removed to avoid confusion. Non-blocking.

</details>

---

<details>
<summary>Details</summary>

### Prior blocking issues — all resolved

**Non-atomic prefs write** (prior issue 1): `_save_prefs()` now uses `tempfile.mkstemp(dir=PREFS_FILE.parent, suffix=".tmp")`, writes via `os.fdopen`, and calls `os.replace(tmp, PREFS_FILE)`. The temporary file is cleaned up with `os.unlink(tmp)` if the write raises — confirmed correct.

**Folder filter prefix collision** (prior issue 2): `run()` now computes `norm_filter = folder_filter.replace("\\", "/").rstrip("/")` and `prefix = norm_filter + "/"`, then checks `relative_path == norm_filter or relative_path.startswith(prefix)`. A filter of `"HR"` no longer matches `"HR-archive/doc.txt"` — confirmed.

**Path separator sensitivity** (prior issue 3): `_build_sidebar()` applies `.replace("\\", "/")` when building `rel_str`. `_set_folder()` normalises the stored value on write. `run()` normalises `relative_path` on comparison. All three sites are aligned — confirmed.

**viewer_box.see() after disabled** (prior issue 4): `_open_viewer()` now calls `self.viewer_box.see(first_index)` before `self.viewer_box.configure(state="disabled")`. The comment in the code explicitly calls out the reason — confirmed.

### Duplicate lines in _refresh_types()

```python
def _refresh_types(self):
    types = sorted({r.get("doc_type") for r in self.catalog if r.get("doc_type")})
    self.type_menu.configure(values=[self.ALL_TYPES] + types)   # first
    types = sorted({r.get("doc_type") for r in self.catalog if r.get("doc_type")})
    self.type_menu.configure(values=[self.ALL_TYPES] + types)   # duplicate — no-op
    if self.type_var.get() not in [self.ALL_TYPES] + types:
        self.type_var.set(self.ALL_TYPES)
```

The second pair is a copy-paste artifact. The method works correctly because the guard `if self.type_var.get() not in [...]` only runs once, after the final value of `types`. No behavioral impact.

### History dropdown re-pack position

The prior review flagged a possible visual ordering issue when `_show_history()` calls `pack()` after `pack_forget()`. Tkinter's pack manager preserves a widget's slot in the pack order even after `pack_forget()`; calling `pack()` again re-inserts the widget at its original position between `top` and `progress_bar`. Confirmed: no layout fix is needed.

### Test coverage

The test suite does not instantiate the GUI, so none of the three new features are covered by automated tests. The folder filter logic in `run()` — the most functionally significant piece — has no direct unit test. A test that constructs mock catalog rows with `relative_path` values covering the prefix-collision case, the Windows-path case, and the exact-match case would validate the fix and prevent regression. This is non-blocking but worth adding.

</details>

---

<details>
<summary>File map</summary>

| File | What changed |
|------|-------------|
| `index.py` | Added `_load_prefs`, `_save_prefs`, `_build_sidebar`, `_set_folder`, `_build_history_frame`, `_show_history`, `_hide_history`, `_clear_history`, `_open_viewer`, `_close_viewer`; restructured layout with `_split` container and sidebar; modified `start()`, `reload()`, `toggle_theme()`, `_doc_card()`; all four prior blocking issues resolved |

</details>
