#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

import c2c_tag_reshuffle_tool as tagtool


if not tagtool.PIL_AVAILABLE:
    print("Pillow and numpy are required for the c2c province shape tool.", file=sys.stderr)
    raise SystemExit(2)

np = tagtool.np
Image = tagtool.Image
ImageTk = tagtool.ImageTk


DEFAULT_GAME_ROOT = tagtool.DEFAULT_GAME_ROOT
DEFAULT_USFP_ROOT = tagtool.DEFAULT_USFP_ROOT

DARK_BG = "#14181e"
DARK_PANEL = "#1b222c"
DARK_ELEVATED = "#222b36"
DARK_BORDER = "#344150"
DARK_FG = "#e8edf4"
DARK_MUTED = "#aab6c6"
ACCENT = "#4d9cff"
SELECTION = "#f7d154"
WARNING = "#ffbe76"

MIN_SCALE = 0.08
MAX_SCALE = 2.50
ZOOM_FACTOR = 1.35
RENDER_MARGIN = 320
UNDO_LIMIT = 30

MODE_TAGS = "Tag overlay"
MODE_STATES = "State overlay"
MODE_RAW = "Raw provinces"
COLOR_MODES = [MODE_TAGS, MODE_STATES, MODE_RAW]

BRUSH_MODE_PAINT = "Paint province"
BRUSH_MODE_PUSH = "Push border"
BRUSH_MODE_PUSH_TAG = "Push tag border"
BRUSH_MODE_PUSH_STATE = "Push state border"
BRUSH_MODES = [BRUSH_MODE_PAINT, BRUSH_MODE_PUSH, BRUSH_MODE_PUSH_TAG, BRUSH_MODE_PUSH_STATE]


@dataclass
class ImagePatch:
    bbox: tuple[int, int, int, int]
    before: object
    after: object


def repo_root_from_script() -> Path:
    script_path = Path(__file__).resolve()
    for candidate in script_path.parents:
        if (candidate / "mod").is_dir() and (candidate / "script").is_dir():
            return candidate
    return script_path.parents[2]


def pack_rgb_array(rgb: object) -> object:
    return (
        rgb[:, :, 0].astype(np.int32) << 16
    ) + (
        rgb[:, :, 1].astype(np.int32) << 8
    ) + rgb[:, :, 2].astype(np.int32)


def packed_to_rgb(value: int) -> tuple[int, int, int]:
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


def blend_with_color(arr: object, mask: object, color: tuple[int, int, int], amount: float) -> None:
    if not np.any(mask):
        return
    base = arr[mask].astype(np.float32)
    tint = np.array(color, dtype=np.float32)
    arr[mask] = np.clip(base * (1.0 - amount) + tint * amount, 0, 255).astype(np.uint8)


def boundary_between(values: object, valid: object | None = None) -> object:
    boundary = np.zeros(values.shape, dtype=bool)
    if values.size == 0:
        return boundary
    vertical = values[1:, :] != values[:-1, :]
    horizontal = values[:, 1:] != values[:, :-1]
    if valid is not None:
        vertical &= valid[1:, :] | valid[:-1, :]
        horizontal &= valid[:, 1:] | valid[:, :-1]
    boundary[1:, :] |= vertical
    boundary[:-1, :] |= vertical
    boundary[:, 1:] |= horizontal
    boundary[:, :-1] |= horizontal
    return boundary


def thicken(mask: object, passes: int = 1) -> object:
    result = mask.copy()
    for _ in range(passes):
        grown = result.copy()
        grown[1:, :] |= result[:-1, :]
        grown[:-1, :] |= result[1:, :]
        grown[:, 1:] |= result[:, :-1]
        grown[:, :-1] |= result[:, 1:]
        result = grown
    return result


class ProvinceShapeRepository:
    def __init__(self, root: Path, game_root: Path | None, upstream_mod: Path | None) -> None:
        self.root = root
        self.mod_root = root / "mod"
        self.tag_repo = tagtool.C2CTagRepository(root, game_root, upstream_mod)
        self.province_image_path = self.mod_root / "map_data" / "provinces.png"
        self.rgb = None
        self.visible_map_bounds: tuple[int, int, int, int] | None = None
        self.known_provinces: set[str] = set()
        self.known_values = np.array([], dtype=np.int32)
        self.original_known_values = np.array([], dtype=np.int32)
        self.state_values: dict[str, object] = {}
        self.known_lookup = np.zeros(1 << 24, dtype=bool)
        self.original_present_lookup = np.zeros(1 << 24, dtype=bool)
        self.state_lookup = np.zeros(1 << 24, dtype=np.uint16)
        self.history_owner_lookup = np.zeros(1 << 24, dtype=np.uint16)
        self.startup_owner_lookup = np.zeros(1 << 24, dtype=np.uint16)
        self.state_id_to_index: dict[str, int] = {}
        self.owner_tag_to_index: dict[str, int] = {}
        self.state_color_palette = np.array([[18, 21, 26]], dtype=np.uint8)
        self.owner_color_palette = np.array([[72, 76, 84]], dtype=np.uint8)

    def load(self) -> None:
        self.tag_repo.load(load_image=True)
        loaded_path = self.tag_repo.province_image_path
        if loaded_path is None:
            raise FileNotFoundError("Could not locate c2c provinces.png.")
        expected_paths = {
            (self.mod_root / "map_data" / "provinces.png").resolve(),
            (self.mod_root / "map" / "data" / "provinces.png").resolve(),
        }
        if loaded_path.resolve() not in expected_paths:
            raise FileNotFoundError(
                "The tool only edits c2c's provinces.png, but the loaded image came from "
                f"{loaded_path}."
            )
        self.province_image_path = loaded_path.resolve()
        self.reload_image()
        self.visible_map_bounds = self.tag_repo.visible_map_bounds
        self.known_provinces = set(self.tag_repo.province_to_state)
        known_values = [tagtool.province_to_packed(province) for province in sorted(self.known_provinces)]
        self.known_values = np.array(known_values, dtype=np.int32)
        self.original_known_values = self.present_known_values()
        self.original_present_lookup[:] = False
        self.original_present_lookup[self.original_known_values] = True
        self.state_values = {
            state_id: np.array(
                [tagtool.province_to_packed(province) for province in region.provinces],
                dtype=np.int32,
            )
            for state_id, region in self.tag_repo.state_regions.items()
        }
        self.build_lookup_tables()

    def build_lookup_tables(self) -> None:
        self.known_lookup[:] = False
        self.state_lookup[:] = 0
        self.history_owner_lookup[:] = 0
        self.startup_owner_lookup[:] = 0
        if len(self.known_values):
            self.known_lookup[self.known_values] = True

        state_colors = [[18, 21, 26]]
        self.state_id_to_index = {}
        for state_id in sorted(self.tag_repo.state_regions):
            state_index = len(state_colors)
            self.state_id_to_index[state_id] = state_index
            state_colors.append(list(self.color_for_state(state_id)))
            values = self.state_values.get(state_id)
            if values is not None and len(values):
                self.state_lookup[values] = state_index
        self.state_color_palette = np.array(state_colors, dtype=np.uint8)

        owner_tags = sorted(
            {
                tag
                for tag in list(self.tag_repo.history_ownership.values()) + list(self.tag_repo.ownership.values())
                if tag
            }
        )
        owner_colors = [[72, 76, 84]]
        self.owner_tag_to_index = {}
        for tag in owner_tags:
            owner_index = len(owner_colors)
            self.owner_tag_to_index[tag] = owner_index
            owner_colors.append(list(self.tag_repo.color_for_tag(tag)))
        self.owner_color_palette = np.array(owner_colors, dtype=np.uint8)

        for province in self.known_provinces:
            value = tagtool.province_to_packed(province)
            history_owner = self.tag_repo.history_ownership.get(province, "")
            startup_owner = self.tag_repo.ownership.get(province, "")
            self.history_owner_lookup[value] = self.owner_tag_to_index.get(history_owner, 0)
            self.startup_owner_lookup[value] = self.owner_tag_to_index.get(startup_owner, 0)

    def reload_image(self) -> None:
        image = Image.open(self.province_image_path).convert("RGB")
        image.load()
        self.rgb = np.array(image, dtype=np.uint8)

    def present_known_values(self) -> object:
        if self.rgb is None or len(self.known_values) == 0:
            return np.array([], dtype=np.int32)
        packed = pack_rgb_array(self.rgb)
        present = np.unique(packed.reshape(-1))
        return present[np.isin(present, self.known_values)]

    def missing_original_provinces(self) -> list[str]:
        if self.rgb is None:
            return []
        current = self.present_known_values()
        missing = self.original_known_values[~np.isin(self.original_known_values, current)]
        return [tagtool.packed_to_province(value) for value in missing.tolist()]

    def absent_loaded_provinces(self) -> list[str]:
        if self.rgb is None:
            return []
        current = self.present_known_values()
        absent = self.known_values[~np.isin(self.known_values, current)]
        return [tagtool.packed_to_province(value) for value in absent.tolist()]

    def province_was_present_on_load(self, province: str) -> bool:
        value = tagtool.province_to_packed(province)
        return bool(self.original_present_lookup[value])

    def state_for_packed(self, packed: int) -> str | None:
        return self.tag_repo.province_to_state.get(tagtool.packed_to_province(packed))

    def owner_for_packed(self, packed: int, include_startup_effects: bool) -> str:
        province = tagtool.packed_to_province(packed)
        if include_startup_effects:
            return self.tag_repo.ownership.get(province, "")
        return self.tag_repo.history_ownership.get(province, "")

    def color_for_state(self, state_id: str) -> tuple[int, int, int]:
        red, green, blue = tagtool.stable_tag_color(state_id)
        return (
            max(45, min(225, red)),
            max(45, min(225, green)),
            max(45, min(225, blue)),
        )

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1]) if self.rgb is not None else 1

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0]) if self.rgb is not None else 1


class ProvinceShapeApp:
    def __init__(self, root: tk.Tk, repository: ProvinceShapeRepository) -> None:
        self.root = root
        self.repository = repository
        self.root.title("c2c Province Shape Tool")
        self.root.geometry("1360x860")
        self.root.minsize(1060, 680)

        self.selected_state: str | None = None
        self.target_province_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Right-click a province to pick the brush color.")
        self.hover_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="")
        self.brush_radius_var = tk.IntVar(value=5)
        self.brush_label_var = tk.StringVar(value="5 px")
        self.brush_mode_var = tk.StringVar(value=BRUSH_MODE_PAINT)
        self.color_mode_var = tk.StringVar(value=MODE_TAGS)
        self.history_only_var = tk.BooleanVar(value=True)
        self.show_province_borders_var = tk.BooleanVar(value=True)
        self.show_state_borders_var = tk.BooleanVar(value=True)
        self.show_tag_borders_var = tk.BooleanVar(value=True)
        self.dim_other_states_var = tk.BooleanVar(value=False)
        self.limit_selected_state_var = tk.BooleanVar(value=True)
        self.limit_known_land_var = tk.BooleanVar(value=True)
        self.show_labels_var = tk.BooleanVar(value=True)

        self.state_display: list[tuple[str, str]] = []
        self.scale = 0.25
        self.pending_view_center: tuple[float, float] | None = None
        self.render_after_id: str | None = None
        self.display_photo = None
        self.selection_photo = None
        self.view_left = 0
        self.view_top = 0
        self.virtual_width = 1
        self.virtual_height = 1
        self.tile_left = 0
        self.tile_top = 0
        self.tile_right = 0
        self.tile_bottom = 0
        self.tile_packed = None
        self.tile_state_index = None
        self.tag_label_bboxes: list[tuple[int, int, int, int]] = []
        self.tag_labels_hidden = False
        self.painting = False
        self.last_paint_source: tuple[int, int] | None = None
        self.active_target_rgb: tuple[int, int, int] | None = None
        self.stroke_bbox: tuple[int, int, int, int] | None = None
        self.stroke_before = None
        self.cursor_canvas_pos: tuple[float, float] | None = None
        self.dirty = False
        self.undo_stack: list[ImagePatch] = []
        self.redo_stack: list[ImagePatch] = []

        self._apply_theme()
        self._build_ui()
        self.refresh_state_list()
        self.select_initial_state()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _apply_theme(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.root.configure(bg=DARK_BG)
        style.configure(".", background=DARK_BG, foreground=DARK_FG, fieldbackground=DARK_ELEVATED)
        style.configure("TFrame", background=DARK_BG)
        style.configure("Panel.TFrame", background=DARK_PANEL)
        style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
        style.configure("Panel.TLabel", background=DARK_PANEL, foreground=DARK_FG)
        style.configure("Muted.TLabel", background=DARK_PANEL, foreground=DARK_MUTED)
        style.configure("Warning.TLabel", background=DARK_PANEL, foreground=WARNING)
        style.configure("TButton", background=DARK_ELEVATED, foreground=DARK_FG)
        style.configure("TCheckbutton", background=DARK_PANEL, foreground=DARK_FG)
        style.configure("TRadiobutton", background=DARK_PANEL, foreground=DARK_FG)
        style.configure("Treeview", background=DARK_ELEVATED, fieldbackground=DARK_ELEVATED, foreground=DARK_FG)
        style.configure("Treeview.Heading", background=DARK_PANEL, foreground=DARK_FG)

    def _build_ui(self) -> None:
        outer = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        right = ttk.Frame(outer, padding=0)
        outer.add(left, weight=0)
        outer.add(right, weight=1)

        ttk.Label(left, text="States", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        search = ttk.Entry(left, textvariable=self.search_var, width=38)
        search.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        search.bind("<KeyRelease>", lambda _event: self.refresh_state_list())

        self.state_listbox = tk.Listbox(
            left,
            width=44,
            height=13,
            bg=DARK_ELEVATED,
            fg=DARK_FG,
            selectbackground=ACCENT,
            highlightthickness=1,
            highlightbackground=DARK_BORDER,
            relief=tk.FLAT,
        )
        self.state_listbox.grid(row=2, column=0, sticky="nsew")
        self.state_listbox.bind("<<ListboxSelect>>", self.on_state_select)

        ttk.Label(left, text="Owner Tags", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 4))
        self.owner_tree = ttk.Treeview(left, columns=("tag", "count"), show="headings", height=7)
        self.owner_tree.heading("tag", text="Tag")
        self.owner_tree.heading("count", text="Provinces")
        self.owner_tree.column("tag", width=110, anchor="w")
        self.owner_tree.column("count", width=80, anchor="e")
        self.owner_tree.grid(row=4, column=0, sticky="ew")
        self.owner_tree.bind("<<TreeviewSelect>>", self.on_owner_tree_select)

        brush = ttk.Frame(left, style="Panel.TFrame")
        brush.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(brush, text="Brush mode", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.brush_mode_combo = ttk.Combobox(brush, textvariable=self.brush_mode_var, values=BRUSH_MODES, state="readonly", width=16)
        self.brush_mode_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.brush_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_brush_mode_change())
        ttk.Label(brush, text="Target province", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.target_combo = ttk.Combobox(brush, textvariable=self.target_province_var, width=16)
        self.target_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        self.target_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_target_changed())
        self.target_combo.bind("<FocusOut>", lambda _event: self.on_target_changed())
        brush.columnconfigure(1, weight=1)

        radius = ttk.Frame(left, style="Panel.TFrame")
        radius.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(radius, text="Brush", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        scale = ttk.Scale(radius, from_=1, to=64, variable=self.brush_radius_var, command=self.on_brush_size_change)
        scale.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Label(radius, textvariable=self.brush_label_var, style="Panel.TLabel", width=6).grid(row=0, column=2, sticky="e")
        radius.columnconfigure(1, weight=1)

        modes = ttk.Frame(left, style="Panel.TFrame")
        modes.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(modes, text="Color mode", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        mode_combo = ttk.Combobox(modes, textvariable=self.color_mode_var, values=COLOR_MODES, state="readonly")
        mode_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        mode_combo.bind("<<ComboboxSelected>>", lambda _event: self.schedule_render())
        modes.columnconfigure(1, weight=1)

        options = ttk.Frame(left, style="Panel.TFrame")
        options.grid(row=8, column=0, sticky="ew", pady=(10, 0))
        checks = [
            ("History ownership only", self.history_only_var, self.on_ownership_mode_change),
            ("Province borders", self.show_province_borders_var, self.schedule_render),
            ("State borders", self.show_state_borders_var, self.schedule_render),
            ("Tag borders", self.show_tag_borders_var, self.schedule_render),
            ("Dim outside selected state", self.dim_other_states_var, self.schedule_render),
            ("Paint only selected state", self.limit_selected_state_var, None),
            ("Paint only loaded land", self.limit_known_land_var, None),
            ("Selected-state tag labels", self.show_labels_var, self.schedule_render),
        ]
        for row, (label, variable, command) in enumerate(checks):
            ttk.Checkbutton(options, text=label, variable=variable, command=command).grid(row=row, column=0, sticky="w")

        buttons = ttk.Frame(left, style="Panel.TFrame")
        buttons.grid(row=9, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="Undo", command=self.undo).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=2)
        ttk.Button(buttons, text="Redo", command=self.redo).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=2)
        ttk.Button(buttons, text="Save provinces.png", command=self.save_image).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        ttk.Button(buttons, text="Reload Image", command=self.reload_image).grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        ttk.Label(left, textvariable=self.summary_var, style="Muted.TLabel", wraplength=320).grid(
            row=10, column=0, sticky="ew", pady=(12, 0)
        )
        ttk.Label(left, textvariable=self.hover_var, style="Muted.TLabel", wraplength=320).grid(
            row=11, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Label(left, textvariable=self.status_var, style="Warning.TLabel", wraplength=320).grid(
            row=12, column=0, sticky="ew", pady=(8, 0)
        )

        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        self.h_scroll = ttk.Scrollbar(right, orient=tk.HORIZONTAL)
        self.v_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL)
        self.canvas = tk.Canvas(
            right,
            bg="#0d1117",
            cursor="none",
            highlightthickness=0,
            xscrollcommand=self.h_scroll.set,
            yscrollcommand=self.v_scroll.set,
        )
        self.h_scroll.configure(command=self.on_xscroll)
        self.v_scroll.configure(command=self.on_yscroll)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_paint_press)
        self.canvas.bind("<B1-Motion>", self.on_paint_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_paint_release)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)
        self.canvas.bind("<ButtonPress-2>", self.start_pan)
        self.canvas.bind("<B2-Motion>", self.do_pan)
        self.canvas.bind("<Leave>", self.on_canvas_leave)
        self.canvas.bind("<Configure>", lambda _event: self.schedule_render(delay=40))
        self.root.bind("<Control-z>", lambda _event: self.undo())
        self.root.bind("<Control-y>", lambda _event: self.redo())

    def refresh_state_list(self) -> None:
        query = self.search_var.get().strip().lower()
        display: list[tuple[str, str]] = []
        for state_id in sorted(self.repository.tag_repo.state_regions):
            if query and query not in state_id.lower():
                continue
            region = self.repository.tag_repo.state_regions[state_id]
            groups = self.repository.tag_repo.state_owner_groups(
                state_id,
                self.current_ownership_by_province(),
            )
            label = f"{state_id}  [{region.source_name}]  {tagtool.format_owner_summary(groups)}"
            display.append((state_id, label))
        self.state_display = display
        self.state_listbox.delete(0, tk.END)
        for _state_id, label in display:
            self.state_listbox.insert(tk.END, label)

    def current_ownership_by_province(self) -> dict[str, str]:
        if self.history_only_var.get():
            return self.repository.tag_repo.history_ownership
        return self.repository.tag_repo.ownership

    def is_push_mode(self) -> bool:
        return self.push_scope() is not None

    def push_scope(self) -> str | None:
        mode = self.brush_mode_var.get()
        if mode == BRUSH_MODE_PUSH:
            return "province"
        if mode == BRUSH_MODE_PUSH_TAG:
            return "tag"
        if mode == BRUSH_MODE_PUSH_STATE:
            return "state"
        return None

    def on_brush_mode_change(self) -> None:
        scope = self.push_scope()
        if scope is None:
            self.target_combo.configure(state="normal")
            self.status_var.set("Province paint mode: right-click picks a province, left-drag paints it.")
        else:
            self.target_combo.configure(state="disabled")
            if scope == "province":
                self.status_var.set("Province border mode: drag from one province toward another to move their border.")
            elif scope == "tag":
                self.status_var.set("Tag border mode: drag inside a tag to push only its outer border.")
            else:
                self.status_var.set("State border mode: drag inside a state to push only its outer border.")
        self.redraw_brush_cursor()

    def on_ownership_mode_change(self) -> None:
        mode = "history ownership" if self.history_only_var.get() else "history plus startup effects"
        self.refresh_owner_tree()
        self.refresh_state_list()
        self.schedule_render()
        self.status_var.set(f"Overlay mode: {mode}.")

    def select_initial_state(self) -> None:
        preferred = "STATE_NORTHWEST_TERRITORIES"
        for index, (state_id, _label) in enumerate(self.state_display):
            if state_id == preferred:
                self.state_listbox.selection_set(index)
                self.select_state(state_id)
                return
        if self.state_display:
            self.state_listbox.selection_set(0)
            self.select_state(self.state_display[0][0])

    def on_state_select(self, _event: object) -> None:
        selection = self.state_listbox.curselection()
        if not selection:
            return
        self.select_state(self.state_display[selection[0]][0])

    def select_state(self, state_id: str) -> None:
        self.selected_state = state_id
        self.refresh_owner_tree()
        region = self.repository.tag_repo.state_regions[state_id]
        provinces = sorted(region.provinces)
        self.target_combo.configure(values=provinces)
        if self.target_province_var.get() not in provinces:
            self.target_province_var.set(provinces[0] if provinces else "")
        self.summary_var.set(
            f"{state_id} from {region.source_name}. Right-click picks a province color; left-drag paints it."
        )
        self.schedule_render()

    def refresh_owner_tree(self) -> None:
        self.owner_tree.delete(*self.owner_tree.get_children())
        if not self.selected_state:
            return
        groups = self.repository.tag_repo.state_owner_groups(
            self.selected_state,
            self.current_ownership_by_province(),
        )
        for tag, provinces in groups.items():
            self.owner_tree.insert("", tk.END, iid=tag, values=(tag, len(provinces)))

    def on_owner_tree_select(self, _event: object) -> None:
        if not self.selected_state:
            return
        selection = self.owner_tree.selection()
        if not selection:
            return
        tag = selection[0]
        groups = self.repository.tag_repo.state_owner_groups(
            self.selected_state,
            self.current_ownership_by_province(),
        )
        provinces = groups.get(tag)
        if provinces:
            self.target_province_var.set(provinces[0])
            self.on_target_changed()

    def select_state_in_list(self, state_id: str) -> None:
        for index, (candidate, _label) in enumerate(self.state_display):
            if candidate == state_id:
                self.state_listbox.selection_clear(0, tk.END)
                self.state_listbox.selection_set(index)
                self.state_listbox.see(index)
                return

    def on_target_changed(self) -> None:
        province = tagtool.normalize_province(self.target_province_var.get())
        if province not in self.repository.known_provinces:
            self.status_var.set(f"{province} is not a loaded province id.")
            return
        if not self.repository.province_was_present_on_load(province):
            self.status_var.set(f"{province} is loaded in state data but was not present in provinces.png.")
            return
        state_id = self.repository.tag_repo.province_to_state.get(province)
        owner = self.current_ownership_by_province().get(province, "")
        self.target_province_var.set(province)
        self.status_var.set(f"Target: {province}  {state_id or 'unknown state'}  {owner or 'no owner'}")
        self.redraw_brush_cursor()

    def on_brush_size_change(self, value: object) -> None:
        radius = max(1, min(64, int(float(value))))
        self.brush_radius_var.set(radius)
        self.brush_label_var.set(f"{radius} px")
        self.redraw_brush_cursor()

    def schedule_render(self, delay: int = 20, replace: bool = True) -> None:
        if self.render_after_id is not None:
            if not replace:
                return
            self.root.after_cancel(self.render_after_id)
        self.render_after_id = self.root.after(delay, self.render_map)

    def render_map(self) -> None:
        self.render_after_id = None
        if self.repository.rgb is None:
            return
        bounds = self.repository.visible_map_bounds or (0, 0, self.repository.width, self.repository.height)
        self.view_left, self.view_top, view_right, view_bottom = bounds
        source_width = view_right - self.view_left
        source_height = view_bottom - self.view_top
        self.virtual_width = max(1, int(source_width * self.scale))
        self.virtual_height = max(1, int(source_height * self.scale))
        self.canvas.configure(scrollregion=(0, 0, self.virtual_width, self.virtual_height))
        self.restore_pending_view_center(self.virtual_width, self.virtual_height)
        self.canvas.update_idletasks()

        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        viewport_left = max(0, int(self.canvas.canvasx(0)))
        viewport_top = max(0, int(self.canvas.canvasy(0)))
        wanted_left = max(0, viewport_left - RENDER_MARGIN)
        wanted_top = max(0, viewport_top - RENDER_MARGIN)
        wanted_right = min(self.virtual_width, viewport_left + viewport_width + RENDER_MARGIN)
        wanted_bottom = min(self.virtual_height, viewport_top + viewport_height + RENDER_MARGIN)

        source_left = max(0, int(math.floor(wanted_left / max(self.scale, 0.0001))))
        source_top = max(0, int(math.floor(wanted_top / max(self.scale, 0.0001))))
        source_right = min(source_width, int(math.ceil(wanted_right / max(self.scale, 0.0001))))
        source_bottom = min(source_height, int(math.ceil(wanted_bottom / max(self.scale, 0.0001))))
        if source_right <= source_left or source_bottom <= source_top:
            return

        tile_left = max(0, int(source_left * self.scale))
        tile_top = max(0, int(source_top * self.scale))
        tile_right = min(self.virtual_width, max(tile_left + 1, int(math.ceil(source_right * self.scale))))
        tile_bottom = min(self.virtual_height, max(tile_top + 1, int(math.ceil(source_bottom * self.scale))))
        width = tile_right - tile_left
        height = tile_bottom - tile_top
        self.tile_left = tile_left
        self.tile_top = tile_top
        self.tile_right = tile_right
        self.tile_bottom = tile_bottom

        source = self.repository.rgb[
            self.view_top + source_top : self.view_top + source_bottom,
            self.view_left + source_left : self.view_left + source_right,
        ]
        scaled = Image.fromarray(source, "RGB").resize((width, height), Image.Resampling.NEAREST)
        raw_arr = np.asarray(scaled, dtype=np.uint8)
        packed = pack_rgb_array(raw_arr)
        self.tile_packed = packed

        rendered, state_index, owner_index = self.render_palette(packed, raw_arr)
        self.tile_state_index = state_index

        if self.show_province_borders_var.get():
            rendered[boundary_between(packed)] = np.array([14, 18, 24], dtype=np.uint8)
        if self.show_tag_borders_var.get():
            rendered[boundary_between(owner_index, owner_index > 0)] = np.array([232, 238, 246], dtype=np.uint8)
        if self.show_state_borders_var.get():
            rendered[thicken(boundary_between(state_index, state_index > 0), 1)] = np.array([247, 209, 84], dtype=np.uint8)
        self.apply_selected_state_outline(rendered, state_index)

        self.display_photo = ImageTk.PhotoImage(Image.fromarray(rendered, "RGB"))
        self.canvas.delete("all")
        self.tag_label_bboxes.clear()
        self.tag_labels_hidden = False
        self.canvas.create_image(tile_left, tile_top, image=self.display_photo, anchor="nw")
        if self.show_labels_var.get():
            self.draw_tag_labels(tile_left, tile_top, state_index, owner_index)
        self.redraw_brush_cursor()

    def render_palette(
        self,
        packed: object,
        raw_arr: object,
    ) -> tuple[object, object, object]:
        color_mode = self.color_mode_var.get()
        selected_state = self.selected_state
        state_index = self.repository.state_lookup[packed]
        if self.history_only_var.get():
            owner_index = self.repository.history_owner_lookup[packed]
        else:
            owner_index = self.repository.startup_owner_lookup[packed]

        if color_mode == MODE_RAW:
            rendered = raw_arr.copy()
        elif color_mode == MODE_STATES:
            rendered = self.repository.state_color_palette[state_index]
        else:
            rendered = self.repository.owner_color_palette[owner_index]

        if selected_state and self.dim_other_states_var.get():
            selected_index = self.repository.state_id_to_index.get(selected_state)
            if selected_index is not None:
                blend_with_color(rendered, state_index != selected_index, (15, 18, 24), 0.72)

        if color_mode == MODE_RAW:
            unknown_mask = state_index == 0
            blend_with_color(rendered, unknown_mask, (10, 12, 16), 0.30)

        return rendered, state_index, owner_index

    def apply_selected_state_outline(self, rendered: object, state_index: object) -> None:
        if not self.selected_state:
            return
        selected_index = self.state_index_for_selected_tile(state_index)
        if selected_index is None:
            return
        selected_mask = state_index == selected_index
        if not np.any(selected_mask):
            return
        padded = np.pad(selected_mask, 1, mode="constant", constant_values=False)
        interior = (
            selected_mask
            & padded[:-2, 1:-1]
            & padded[2:, 1:-1]
            & padded[1:-1, :-2]
            & padded[1:-1, 2:]
        )
        outline = thicken(selected_mask & ~interior, 1)
        rendered[outline] = np.array([255, 246, 132], dtype=np.uint8)

    def state_index_for_selected_tile(self, state_index: object) -> int | None:
        if self.selected_state is None:
            return None
        return self.repository.state_id_to_index.get(self.selected_state)

    def draw_tag_labels(self, tile_left: int, tile_top: int, state_index: object, owner_index: object) -> None:
        if not self.selected_state:
            return
        selected_index = self.repository.state_id_to_index.get(self.selected_state)
        if selected_index is None:
            return
        groups = self.repository.tag_repo.state_owner_groups(
            self.selected_state,
            self.current_ownership_by_province(),
        )
        state_mask = state_index == selected_index
        if not np.any(state_mask):
            return
        for tag in groups:
            tag_index = self.repository.owner_tag_to_index.get(tag)
            if tag_index is None:
                continue
            mask = state_mask & (owner_index == tag_index)
            if not np.any(mask):
                continue
            ys, xs = np.nonzero(mask)
            x = tile_left + int(np.mean(xs))
            y = tile_top + int(np.mean(ys))
            text_id = self.canvas.create_text(
                x,
                y,
                text=tag,
                fill="#ffffff",
                font=("", 12, "bold"),
                tags=("tag_label",),
            )
            bbox = self.canvas.bbox(text_id)
            if bbox is None:
                continue
            x0, y0, x1, y1 = bbox
            label_box = (x0 - 5, y0 - 3, x1 + 5, y1 + 3)
            rect_id = self.canvas.create_rectangle(
                label_box[0],
                label_box[1],
                label_box[2],
                label_box[3],
                fill="#111820",
                outline="#f7d154",
                width=1,
                tags=("tag_label_box",),
            )
            self.tag_label_bboxes.append(label_box)
            self.canvas.tag_lower(rect_id, text_id)

    def update_label_hover(self, canvas_x: float, canvas_y: float) -> None:
        should_hide = any(
            x0 <= canvas_x <= x1 and y0 <= canvas_y <= y1
            for x0, y0, x1, y1 in self.tag_label_bboxes
        )
        if should_hide == self.tag_labels_hidden:
            return
        state = tk.HIDDEN if should_hide else tk.NORMAL
        self.canvas.itemconfigure("tag_label", state=state)
        self.canvas.itemconfigure("tag_label_box", state=state)
        self.tag_labels_hidden = should_hide

    def redraw_brush_cursor(self) -> None:
        self.canvas.delete("brush_cursor")
        if self.cursor_canvas_pos is None:
            return
        canvas_x, canvas_y = self.cursor_canvas_pos
        radius = max(3.0, float(self.brush_radius_var.get()) * self.scale)
        if self.is_push_mode():
            scope = self.push_scope()
            color = "#ffffff" if scope == "tag" else ("#ffef84" if scope == "state" else ACCENT)
        else:
            target_ready = self.target_rgb(silent=True) is not None
            color = SELECTION if target_ready else WARNING
        self.canvas.create_oval(
            canvas_x - radius,
            canvas_y - radius,
            canvas_x + radius,
            canvas_y + radius,
            outline=color,
            width=2,
            tags=("brush_cursor",),
        )
        tick = min(8.0, max(4.0, radius * 0.35))
        self.canvas.create_line(canvas_x - tick, canvas_y, canvas_x + tick, canvas_y, fill=color, width=1, tags=("brush_cursor",))
        self.canvas.create_line(canvas_x, canvas_y - tick, canvas_x, canvas_y + tick, fill=color, width=1, tags=("brush_cursor",))
        self.canvas.tag_raise("brush_cursor")

    def on_canvas_leave(self, _event: tk.Event) -> None:
        self.cursor_canvas_pos = None
        self.canvas.delete("brush_cursor")

    def canvas_to_source(self, canvas_x: float, canvas_y: float) -> tuple[int, int] | None:
        if self.repository.rgb is None:
            return None
        src_x = int(canvas_x / max(self.scale, 0.0001)) + self.view_left
        src_y = int(canvas_y / max(self.scale, 0.0001)) + self.view_top
        if src_x < 0 or src_y < 0 or src_x >= self.repository.width or src_y >= self.repository.height:
            return None
        return src_x, src_y

    def source_to_province(self, src_x: int, src_y: int) -> str:
        red, green, blue = self.repository.rgb[src_y, src_x].tolist()
        return f"x{red:02x}{green:02x}{blue:02x}"

    def packed_at_source(self, src_x: int, src_y: int) -> int | None:
        if self.repository.rgb is None:
            return None
        if src_x < 0 or src_y < 0 or src_x >= self.repository.width or src_y >= self.repository.height:
            return None
        red, green, blue = self.repository.rgb[src_y, src_x].tolist()
        return (int(red) << 16) + (int(green) << 8) + int(blue)

    def packed_allowed_for_brush(self, packed: int) -> bool:
        if self.limit_known_land_var.get() and not self.repository.known_lookup[packed]:
            return False
        if self.limit_selected_state_var.get() and self.selected_state:
            selected_index = self.repository.state_id_to_index.get(self.selected_state)
            if selected_index is not None and self.repository.state_lookup[packed] != selected_index:
                return False
        return True

    def source_allowed_for_group_push(self, packed: int) -> bool:
        if self.limit_known_land_var.get() and not self.repository.known_lookup[packed]:
            return False
        if self.limit_selected_state_var.get() and self.selected_state:
            selected_index = self.repository.state_id_to_index.get(self.selected_state)
            if selected_index is not None and self.repository.state_lookup[packed] != selected_index:
                return False
        return True

    def group_lookup_for_scope(self, scope: str) -> object:
        if scope == "state":
            return self.repository.state_lookup
        if self.history_only_var.get():
            return self.repository.history_owner_lookup
        return self.repository.startup_owner_lookup

    def target_rgb(self, silent: bool = False) -> tuple[int, int, int] | None:
        province = tagtool.normalize_province(self.target_province_var.get())
        if province not in self.repository.known_provinces:
            if not silent:
                self.status_var.set(f"Choose a loaded target province first; {province} is not available.")
            return None
        if not self.repository.province_was_present_on_load(province):
            if not silent:
                self.status_var.set(f"{province} was not present in provinces.png when the tool loaded.")
            return None
        return packed_to_rgb(tagtool.province_to_packed(province))

    def on_right_click(self, event: tk.Event) -> str:
        source = self.canvas_to_source(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if source is None:
            return "break"
        province = self.source_to_province(*source)
        state_id = self.repository.tag_repo.province_to_state.get(province)
        owner = self.current_ownership_by_province().get(province, "")
        if province in self.repository.known_provinces:
            if self.is_push_mode():
                if state_id and state_id != self.selected_state:
                    self.select_state(state_id)
                    self.select_state_in_list(state_id)
                self.status_var.set(f"Picked {province}: {state_id or 'unknown state'}  {owner or 'no owner'}.")
                self.redraw_brush_cursor()
                return "break"
            self.target_province_var.set(province)
            if state_id and state_id != self.selected_state:
                self.select_state(state_id)
                self.select_state_in_list(state_id)
            self.status_var.set(f"Target: {province}  {state_id or 'unknown state'}  {owner or 'no owner'}")
            self.redraw_brush_cursor()
        else:
            self.status_var.set(f"{province} is outside the loaded c2c state set.")
        return "break"

    def on_motion(self, event: tk.Event) -> None:
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.cursor_canvas_pos = (canvas_x, canvas_y)
        self.redraw_brush_cursor()
        self.update_label_hover(canvas_x, canvas_y)
        source = self.canvas_to_source(canvas_x, canvas_y)
        if source is None:
            self.hover_var.set("")
            return
        province = self.source_to_province(*source)
        state_id = self.repository.tag_repo.province_to_state.get(province, "unknown state")
        owner = self.current_ownership_by_province().get(province, "no owner")
        self.hover_var.set(f"{province}  {state_id}  {owner}")

    def on_paint_press(self, event: tk.Event) -> str:
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.cursor_canvas_pos = (canvas_x, canvas_y)
        self.redraw_brush_cursor()
        source = self.canvas_to_source(canvas_x, canvas_y)
        if source is None:
            return "break"
        if self.is_push_mode():
            self.painting = True
            self.last_paint_source = source
            self.active_target_rgb = None
            self.stroke_bbox = None
            self.stroke_before = None
            self.status_var.set("Border push stroke started.")
            return "break"
        self.active_target_rgb = self.target_rgb()
        if self.active_target_rgb is None:
            province = self.source_to_province(*source)
            if province in self.repository.known_provinces:
                self.target_province_var.set(province)
                self.on_target_changed()
            return "break"
        self.painting = True
        self.last_paint_source = source
        self.stroke_bbox = None
        self.stroke_before = None
        self.paint_at(*source)
        return "break"

    def on_paint_drag(self, event: tk.Event) -> str:
        if not self.painting:
            return "break"
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.cursor_canvas_pos = (canvas_x, canvas_y)
        self.redraw_brush_cursor()
        source = self.canvas_to_source(canvas_x, canvas_y)
        if source is None:
            return "break"
        if self.last_paint_source is None:
            self.last_paint_source = source
        self.paint_line(self.last_paint_source, source)
        self.last_paint_source = source
        return "break"

    def on_paint_release(self, _event: tk.Event) -> str:
        if not self.painting:
            return "break"
        self.painting = False
        self.last_paint_source = None
        self.active_target_rgb = None
        self.finish_stroke()
        return "break"

    def paint_line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        radius = max(1, int(self.brush_radius_var.get()))
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        steps = max(1, int(max(abs(dx), abs(dy)) / max(1, radius * 0.55)))
        previous = start
        for step in range(1, steps + 1):
            t = step / steps
            x = int(round(start[0] + dx * t))
            y = int(round(start[1] + dy * t))
            current = (x, y)
            if self.is_push_mode():
                self.push_border_at(previous, current)
            else:
                self.paint_at(x, y)
            previous = current

    def paint_at(self, src_x: int, src_y: int) -> None:
        if self.repository.rgb is None:
            return
        target = self.active_target_rgb or self.target_rgb()
        if target is None:
            return
        radius = max(1, int(self.brush_radius_var.get()))
        x0 = max(0, src_x - radius)
        x1 = min(self.repository.width, src_x + radius + 1)
        y0 = max(0, src_y - radius)
        y1 = min(self.repository.height, src_y + radius + 1)
        if x1 <= x0 or y1 <= y0:
            return

        region = self.repository.rgb[y0:y1, x0:x1]
        yy, xx = np.ogrid[y0:y1, x0:x1]
        mask = ((xx - src_x) * (xx - src_x) + (yy - src_y) * (yy - src_y)) <= radius * radius
        packed = pack_rgb_array(region)
        if self.limit_known_land_var.get():
            mask &= self.repository.known_lookup[packed]
        if self.limit_selected_state_var.get() and self.selected_state:
            selected_index = self.repository.state_id_to_index.get(self.selected_state)
            if selected_index is not None:
                mask &= self.repository.state_lookup[packed] == selected_index
        target_arr = np.array(target, dtype=np.uint8)
        mask &= np.any(region != target_arr, axis=2)
        if not np.any(mask):
            return

        self.ensure_stroke_before((x0, y0, x1, y1))
        region[mask] = target_arr
        self.dirty = True
        self.schedule_render(delay=24, replace=False)

    def push_border_at(self, previous: tuple[int, int], current: tuple[int, int]) -> None:
        scope = self.push_scope()
        if scope == "province":
            self.push_province_border_at(previous, current)
        elif scope in {"tag", "state"}:
            self.push_group_border_at(previous, current, scope)

    def push_province_border_at(self, previous: tuple[int, int], current: tuple[int, int]) -> None:
        if self.repository.rgb is None:
            return
        radius = max(1, int(self.brush_radius_var.get()))
        source_packed, dest_packed = self.infer_push_pair(previous, current, radius)
        if source_packed is None or dest_packed is None or source_packed == dest_packed:
            return
        if not self.packed_allowed_for_brush(source_packed) or not self.packed_allowed_for_brush(dest_packed):
            return

        src_x, src_y = current
        x0 = max(0, src_x - radius)
        x1 = min(self.repository.width, src_x + radius + 1)
        y0 = max(0, src_y - radius)
        y1 = min(self.repository.height, src_y + radius + 1)
        if x1 <= x0 or y1 <= y0:
            return

        region = self.repository.rgb[y0:y1, x0:x1]
        yy, xx = np.ogrid[y0:y1, x0:x1]
        mask = ((xx - src_x) * (xx - src_x) + (yy - src_y) * (yy - src_y)) <= radius * radius
        packed = pack_rgb_array(region)
        mask &= packed == dest_packed
        if self.limit_known_land_var.get():
            mask &= self.repository.known_lookup[packed]
        if self.limit_selected_state_var.get() and self.selected_state:
            selected_index = self.repository.state_id_to_index.get(self.selected_state)
            if selected_index is not None:
                mask &= self.repository.state_lookup[packed] == selected_index
        if not np.any(mask):
            return

        self.ensure_stroke_before((x0, y0, x1, y1))
        region[mask] = np.array(packed_to_rgb(source_packed), dtype=np.uint8)
        self.dirty = True
        self.schedule_render(delay=24, replace=False)

    def push_group_border_at(self, previous: tuple[int, int], current: tuple[int, int], scope: str) -> None:
        if self.repository.rgb is None:
            return
        radius = max(1, int(self.brush_radius_var.get()))
        inferred = self.infer_group_push_pair(previous, current, radius, scope)
        if inferred is None:
            return
        source_packed, source_group, dest_group = inferred
        if source_group == 0 or dest_group == 0 or source_group == dest_group:
            return
        if not self.source_allowed_for_group_push(source_packed):
            return

        src_x, src_y = current
        x0 = max(0, src_x - radius)
        x1 = min(self.repository.width, src_x + radius + 1)
        y0 = max(0, src_y - radius)
        y1 = min(self.repository.height, src_y + radius + 1)
        if x1 <= x0 or y1 <= y0:
            return

        region = self.repository.rgb[y0:y1, x0:x1]
        yy, xx = np.ogrid[y0:y1, x0:x1]
        mask = ((xx - src_x) * (xx - src_x) + (yy - src_y) * (yy - src_y)) <= radius * radius
        packed = pack_rgb_array(region)
        group_lookup = self.group_lookup_for_scope(scope)
        group_index = group_lookup[packed]
        mask &= group_index == dest_group
        if self.limit_known_land_var.get():
            mask &= self.repository.known_lookup[packed]
        if not np.any(mask):
            return

        self.ensure_stroke_before((x0, y0, x1, y1))
        region[mask] = np.array(packed_to_rgb(source_packed), dtype=np.uint8)
        self.dirty = True
        self.schedule_render(delay=24, replace=False)

    def infer_group_push_pair(
        self,
        previous: tuple[int, int],
        current: tuple[int, int],
        radius: int,
        scope: str,
    ) -> tuple[int, int, int] | None:
        dx = current[0] - previous[0]
        dy = current[1] - previous[1]
        distance = math.hypot(dx, dy)
        if distance <= 0:
            return None
        ux = dx / distance
        uy = dy / distance
        offset = max(1.0, radius * 0.75)
        behind = (
            int(round(current[0] - ux * offset)),
            int(round(current[1] - uy * offset)),
        )
        ahead = (
            int(round(current[0] + ux * offset)),
            int(round(current[1] + uy * offset)),
        )
        group_lookup = self.group_lookup_for_scope(scope)
        center_packed = self.packed_at_source(*current)
        center_group = int(group_lookup[center_packed]) if center_packed is not None else 0
        preferred_source = None
        if center_packed is not None and center_group != 0 and self.source_allowed_for_group_push(center_packed):
            preferred_source = (center_packed, center_group)
            dest_packed = self.packed_at_source(*ahead)
            if dest_packed is not None:
                dest_group = int(group_lookup[dest_packed])
                if dest_group != 0 and dest_group != center_group:
                    return center_packed, center_group, dest_group

        source_packed = self.packed_at_source(*behind)
        dest_packed = self.packed_at_source(*ahead)
        direct = self.group_pair_from_samples(source_packed, dest_packed, group_lookup, preferred_source)
        if direct is not None:
            return direct

        source_packed = self.packed_at_source(*previous)
        dest_packed = self.packed_at_source(*current)
        direct = self.group_pair_from_samples(source_packed, dest_packed, group_lookup, preferred_source)
        if direct is not None:
            return direct

        return self.infer_group_push_pair_from_brush(current, ux, uy, radius, group_lookup, preferred_source)

    def group_pair_from_samples(
        self,
        source_packed: int | None,
        dest_packed: int | None,
        group_lookup: object,
        preferred_source: tuple[int, int] | None = None,
    ) -> tuple[int, int, int] | None:
        if source_packed is None or dest_packed is None or source_packed == dest_packed:
            return None
        source_group = int(group_lookup[source_packed])
        dest_group = int(group_lookup[dest_packed])
        if source_group == 0 or dest_group == 0 or source_group == dest_group:
            return None
        if preferred_source is not None:
            preferred_packed, preferred_group = preferred_source
            if dest_group != preferred_group:
                return preferred_packed, preferred_group, dest_group
        if not self.source_allowed_for_group_push(source_packed):
            return None
        return source_packed, source_group, dest_group

    def infer_group_push_pair_from_brush(
        self,
        current: tuple[int, int],
        ux: float,
        uy: float,
        radius: int,
        group_lookup: object,
        preferred_source: tuple[int, int] | None = None,
    ) -> tuple[int, int, int] | None:
        if self.repository.rgb is None:
            return None
        src_x, src_y = current
        x0 = max(0, src_x - radius)
        x1 = min(self.repository.width, src_x + radius + 1)
        y0 = max(0, src_y - radius)
        y1 = min(self.repository.height, src_y + radius + 1)
        if x1 <= x0 or y1 <= y0:
            return None

        region = self.repository.rgb[y0:y1, x0:x1]
        yy, xx = np.ogrid[y0:y1, x0:x1]
        circle = ((xx - src_x) * (xx - src_x) + (yy - src_y) * (yy - src_y)) <= radius * radius
        packed = pack_rgb_array(region)
        if self.limit_known_land_var.get():
            circle &= self.repository.known_lookup[packed]
        if not np.any(circle):
            return None

        group_index = group_lookup[packed]
        projection = (xx - src_x) * ux + (yy - src_y) * uy
        trailing = circle & (projection <= -max(1.0, radius * 0.15))
        leading = circle & (projection >= max(1.0, radius * 0.15))

        if preferred_source is not None:
            source_packed, source_group = preferred_source
        else:
            source_group = self.dominant_index(group_index[trailing])
            if source_group is None:
                source_group = self.dominant_index(group_index[circle])
            if source_group is None:
                return None

            source_mask = circle & (group_index == source_group)
            allowed_source_mask = source_mask & self.allowed_source_mask(packed)
            if np.any(allowed_source_mask):
                source_mask = allowed_source_mask
            source_packed = self.dominant_packed(packed[source_mask & trailing])
            if source_packed is None:
                source_packed = self.dominant_packed(packed[source_mask])
            if source_packed is None or not self.source_allowed_for_group_push(source_packed):
                return None

        leading_dest = leading & (group_index != source_group) & (group_index != 0)
        dest_group = self.dominant_index(group_index[leading_dest])
        if dest_group is None:
            any_dest = circle & (group_index != source_group) & (group_index != 0)
            dest_group = self.dominant_index(group_index[any_dest])
        if dest_group is None:
            return None
        return source_packed, source_group, dest_group

    def allowed_source_mask(self, packed: object) -> object:
        mask = np.ones(packed.shape, dtype=bool)
        if self.limit_known_land_var.get():
            mask &= self.repository.known_lookup[packed]
        if self.limit_selected_state_var.get() and self.selected_state:
            selected_index = self.repository.state_id_to_index.get(self.selected_state)
            if selected_index is not None:
                mask &= self.repository.state_lookup[packed] == selected_index
        return mask

    def infer_push_pair(
        self,
        previous: tuple[int, int],
        current: tuple[int, int],
        radius: int,
    ) -> tuple[int | None, int | None]:
        dx = current[0] - previous[0]
        dy = current[1] - previous[1]
        distance = math.hypot(dx, dy)
        if distance <= 0:
            return None, None
        ux = dx / distance
        uy = dy / distance
        offset = max(1.0, radius * 0.75)
        behind = (
            int(round(current[0] - ux * offset)),
            int(round(current[1] - uy * offset)),
        )
        ahead = (
            int(round(current[0] + ux * offset)),
            int(round(current[1] + uy * offset)),
        )
        source_packed = self.packed_at_source(*behind)
        dest_packed = self.packed_at_source(*ahead)
        if source_packed is not None and dest_packed is not None and source_packed != dest_packed:
            return source_packed, dest_packed

        source_packed = self.packed_at_source(*previous)
        dest_packed = self.packed_at_source(*current)
        if source_packed is not None and dest_packed is not None and source_packed != dest_packed:
            return source_packed, dest_packed

        return self.infer_push_pair_from_brush(current, ux, uy, radius)

    def infer_push_pair_from_brush(
        self,
        current: tuple[int, int],
        ux: float,
        uy: float,
        radius: int,
    ) -> tuple[int | None, int | None]:
        if self.repository.rgb is None:
            return None, None
        src_x, src_y = current
        x0 = max(0, src_x - radius)
        x1 = min(self.repository.width, src_x + radius + 1)
        y0 = max(0, src_y - radius)
        y1 = min(self.repository.height, src_y + radius + 1)
        if x1 <= x0 or y1 <= y0:
            return None, None

        region = self.repository.rgb[y0:y1, x0:x1]
        yy, xx = np.ogrid[y0:y1, x0:x1]
        circle = ((xx - src_x) * (xx - src_x) + (yy - src_y) * (yy - src_y)) <= radius * radius
        packed = pack_rgb_array(region)
        if self.limit_known_land_var.get():
            circle &= self.repository.known_lookup[packed]
        if self.limit_selected_state_var.get() and self.selected_state:
            selected_index = self.repository.state_id_to_index.get(self.selected_state)
            if selected_index is not None:
                circle &= self.repository.state_lookup[packed] == selected_index
        if not np.any(circle):
            return None, None

        projection = (xx - src_x) * ux + (yy - src_y) * uy
        trailing = circle & (projection <= -max(1.0, radius * 0.15))
        leading = circle & (projection >= max(1.0, radius * 0.15))
        source_packed = self.dominant_packed(packed[trailing])
        dest_packed = self.dominant_packed(packed[leading])
        if source_packed is not None and dest_packed is not None and source_packed != dest_packed:
            return source_packed, dest_packed
        return None, None

    def dominant_packed(self, values: object) -> int | None:
        if values.size == 0:
            return None
        unique, counts = np.unique(values, return_counts=True)
        return int(unique[int(np.argmax(counts))])

    def dominant_index(self, values: object) -> int | None:
        if values.size == 0:
            return None
        values = values[values != 0]
        if values.size == 0:
            return None
        unique, counts = np.unique(values, return_counts=True)
        return int(unique[int(np.argmax(counts))])

    def ensure_stroke_before(self, bbox: tuple[int, int, int, int]) -> None:
        if self.stroke_bbox is None:
            x0, y0, x1, y1 = bbox
            self.stroke_bbox = bbox
            self.stroke_before = self.repository.rgb[y0:y1, x0:x1].copy()
            return
        old_x0, old_y0, old_x1, old_y1 = self.stroke_bbox
        x0, y0, x1, y1 = bbox
        new_bbox = (min(old_x0, x0), min(old_y0, y0), max(old_x1, x1), max(old_y1, y1))
        if new_bbox == self.stroke_bbox:
            return
        nx0, ny0, nx1, ny1 = new_bbox
        expanded_before = self.repository.rgb[ny0:ny1, nx0:nx1].copy()
        expanded_before[
            old_y0 - ny0 : old_y1 - ny0,
            old_x0 - nx0 : old_x1 - nx0,
        ] = self.stroke_before
        self.stroke_bbox = new_bbox
        self.stroke_before = expanded_before

    def finish_stroke(self) -> None:
        if self.stroke_bbox is None or self.stroke_before is None:
            return
        x0, y0, x1, y1 = self.stroke_bbox
        after = self.repository.rgb[y0:y1, x0:x1].copy()
        if np.any(after != self.stroke_before):
            self.undo_stack.append(ImagePatch(self.stroke_bbox, self.stroke_before, after))
            if len(self.undo_stack) > UNDO_LIMIT:
                self.undo_stack.pop(0)
            self.redo_stack.clear()
            changed = int(np.count_nonzero(np.any(after != self.stroke_before, axis=2)))
            self.status_var.set(f"Changed {changed} pixel(s).")
        self.stroke_bbox = None
        self.stroke_before = None

    def undo(self) -> str:
        if not self.undo_stack:
            self.status_var.set("Nothing to undo.")
            return "break"
        patch = self.undo_stack.pop()
        x0, y0, x1, y1 = patch.bbox
        self.repository.rgb[y0:y1, x0:x1] = patch.before
        self.redo_stack.append(patch)
        self.dirty = True
        self.schedule_render()
        self.status_var.set("Undid last brush stroke.")
        return "break"

    def redo(self) -> str:
        if not self.redo_stack:
            self.status_var.set("Nothing to redo.")
            return "break"
        patch = self.redo_stack.pop()
        x0, y0, x1, y1 = patch.bbox
        self.repository.rgb[y0:y1, x0:x1] = patch.after
        self.undo_stack.append(patch)
        self.dirty = True
        self.schedule_render()
        self.status_var.set("Redid brush stroke.")
        return "break"

    def save_image(self) -> None:
        if self.repository.rgb is None:
            return
        missing = self.repository.missing_original_provinces()
        if missing:
            shown = ", ".join(missing[:12])
            extra = len(missing) - 12
            if extra > 0:
                shown += f", ...and {extra} more"
            messagebox.showerror(
                "Province colors missing",
                "Saving is blocked because these loaded province colors no longer appear in provinces.png:\n\n"
                f"{shown}\n\nPaint each province color back somewhere before saving.",
            )
            return
        try:
            Image.fromarray(self.repository.rgb, "RGB").save(self.repository.province_image_path)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            self.status_var.set("Save failed.")
            return
        self.repository.original_known_values = self.repository.present_known_values()
        self.repository.original_present_lookup[:] = False
        self.repository.original_present_lookup[self.repository.original_known_values] = True
        self.dirty = False
        self.status_var.set(f"Saved {self.repository.province_image_path}.")
        messagebox.showinfo("Saved", f"Saved {self.repository.province_image_path}.")

    def reload_image(self) -> None:
        if self.dirty and not messagebox.askyesno("Discard unsaved edits?", "Reloading will discard unsaved brush edits. Continue?"):
            return
        self.repository.reload_image()
        self.repository.original_known_values = self.repository.present_known_values()
        self.repository.original_present_lookup[:] = False
        self.repository.original_present_lookup[self.repository.original_known_values] = True
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.schedule_render()
        self.status_var.set("Reloaded provinces.png from disk.")

    def on_mousewheel(self, event: tk.Event) -> str:
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)
        old_scale = self.scale
        steps = max(1, min(6, abs(int(delta)) // 120 if delta else 1))
        if num == 4 or delta > 0:
            self.scale = min(MAX_SCALE, self.scale * (ZOOM_FACTOR ** steps))
        elif num == 5 or delta < 0:
            self.scale = max(MIN_SCALE, self.scale / (ZOOM_FACTOR ** steps))
        if self.scale != old_scale:
            old_width, old_height = self.render_size_for_scale(old_scale)
            self.remember_zoom_center(old_width, old_height)
            self.schedule_render()
        return "break"

    def render_size_for_scale(self, scale: float) -> tuple[int, int]:
        left, top, right, bottom = self.repository.visible_map_bounds or (0, 0, self.repository.width, self.repository.height)
        return max(1, int((right - left) * scale)), max(1, int((bottom - top) * scale))

    def remember_zoom_center(self, width: int, height: int) -> None:
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        center_x = self.canvas.canvasx(viewport_width / 2)
        center_y = self.canvas.canvasy(viewport_height / 2)
        self.pending_view_center = (
            max(0.0, min(1.0, center_x / max(1, width))),
            max(0.0, min(1.0, center_y / max(1, height))),
        )

    def restore_pending_view_center(self, width: int, height: int) -> None:
        if self.pending_view_center is None:
            return
        rel_x, rel_y = self.pending_view_center
        self.pending_view_center = None
        self.canvas.update_idletasks()
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        left = max(0.0, min(max(0, width - viewport_width), rel_x * width - viewport_width / 2))
        top = max(0.0, min(max(0, height - viewport_height), rel_y * height - viewport_height / 2))
        self.canvas.xview_moveto(left / max(1, width))
        self.canvas.yview_moveto(top / max(1, height))

    def viewport_needs_render(self) -> bool:
        if self.display_photo is None:
            return True
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        viewport_left = int(self.canvas.canvasx(0))
        viewport_top = int(self.canvas.canvasy(0))
        viewport_right = viewport_left + viewport_width
        viewport_bottom = viewport_top + viewport_height
        cushion = max(48, RENDER_MARGIN // 3)
        return (
            viewport_left < self.tile_left + cushion
            or viewport_top < self.tile_top + cushion
            or viewport_right > self.tile_right - cushion
            or viewport_bottom > self.tile_bottom - cushion
        )

    def on_xscroll(self, *args: object) -> None:
        self.canvas.xview(*args)
        if self.viewport_needs_render():
            self.schedule_render(delay=12, replace=False)

    def on_yscroll(self, *args: object) -> None:
        self.canvas.yview(*args)
        if self.viewport_needs_render():
            self.schedule_render(delay=12, replace=False)

    def start_pan(self, event: tk.Event) -> str:
        self.canvas.scan_mark(event.x, event.y)
        return "break"

    def do_pan(self, event: tk.Event) -> str:
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        if self.viewport_needs_render():
            self.schedule_render(delay=12, replace=False)
        return "break"

    def on_close(self) -> None:
        if self.dirty and not messagebox.askyesno("Unsaved brush edits", "Close without saving provinces.png?"):
            return
        self.root.destroy()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="c2c provinces.png shape painter with state and tag overlays")
    parser.add_argument("--repo", default=None, help="Repository root. Defaults to the parent of script/.")
    parser.add_argument("--game-root", default=str(DEFAULT_GAME_ROOT), help="Victoria 3 install root.")
    parser.add_argument("--upstream-mod", default=str(DEFAULT_USFP_ROOT), help="Optional USFP/Hail, Columbia! root.")
    parser.add_argument("--check", action="store_true", help="Load data and print a summary instead of opening the GUI.")
    return parser.parse_args(argv)


def build_repository(args: argparse.Namespace) -> ProvinceShapeRepository:
    repo_root = Path(args.repo).resolve() if args.repo else repo_root_from_script()
    game_root = Path(args.game_root).resolve() if args.game_root else DEFAULT_GAME_ROOT
    upstream = Path(args.upstream_mod).resolve() if args.upstream_mod else DEFAULT_USFP_ROOT
    repository = ProvinceShapeRepository(repo_root, game_root if game_root.exists() else None, upstream)
    repository.load()
    return repository


def run_check(repository: ProvinceShapeRepository) -> int:
    width = repository.width
    height = repository.height
    print(f"Province image: {repository.province_image_path}")
    print(f"Image size: {width}x{height}")
    print(f"Loaded state regions: {len(repository.tag_repo.state_regions)}")
    print(f"Loaded state province ids: {len(repository.known_provinces)}")
    print(f"Visible map bounds: {repository.visible_map_bounds or 'full image'}")
    print(f"Ownership tags: {len(set(repository.tag_repo.history_ownership.values()))}")
    absent = repository.absent_loaded_provinces()
    print(f"Absent loaded province colors: {len(absent)}")
    return 0 if width > 1 and height > 1 and repository.known_provinces and not absent else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        repository = build_repository(args)
    except Exception as exc:
        print(f"Failed to load province shape tool data: {exc}", file=sys.stderr)
        return 1
    if args.check:
        return run_check(repository)
    root = tk.Tk()
    ProvinceShapeApp(root, repository)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())






