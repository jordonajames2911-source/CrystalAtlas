from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk


APP_NAME = "CrystalAtlas"
CONFIG_FILENAME = "crystalatlas_settings.json"
LEGACY_CONFIG_FILENAME = "well_plate_collator_settings.json"

BUILTIN_FILENAME_PRESETS = {
    "Plate_A1_D1": r"^(?P<plate>.+)_(?P<well>[A-Za-z]+\d+)_[Dd](?P<drop>\d+)$",
    "A1_D1": r"^(?P<well>[A-Za-z]+\d+)_[Dd](?P<drop>\d+)$",
}

PLATE_FORMATS = {
    "24-well (4 × 6)": (4, 6),
    "48-well (6 × 8)": (6, 8),
    "96-well (8 × 12)": (8, 12),
    "384-well (16 × 24)": (16, 24),
    "Custom": None,
}
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


def resource_path(filename: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / filename


def app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("APPDATA", Path.home()))
    else:
        root = Path.home() / ".config"
    folder = root / "CrystalAtlas"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def spreadsheet_letters(count: int) -> list[str]:
    values: list[str] = []
    for number in range(1, count + 1):
        n = number
        result = ""
        while n:
            n, remainder = divmod(n - 1, 26)
            result = chr(65 + remainder) + result
        values.append(result)
    return values


def split_labels(text: str, count: int, axis: str) -> list[str]:
    raw = [item.strip() for item in text.split(",") if item.strip()]
    if raw:
        if len(raw) != count:
            raise ValueError(f"{axis} labels contains {len(raw)} values but the grid requires {count}.")
        return raw
    return spreadsheet_letters(count) if axis == "Row" else [str(i) for i in range(1, count + 1)]


@dataclass
class AppConfig:
    rows: int = 8
    columns: int = 12
    row_labels: str = ""
    column_labels: str = ""
    well_pitch_x_mm: float = 10.0
    well_pitch_y_mm: float = 10.0

    drops_per_well: int = 9
    drop_columns: int = 3
    drop_rows: int = 3
    drop_prefix: str = "D"

    filename_regex: str = r"^(?P<plate>.+)_(?P<well>[A-Za-z]+\d+)_[Dd](?P<drop>\d+)$"
    default_plate_name: str = "Plate1"
    filename_presets: dict[str, str] = field(default_factory=dict)
    selected_filename_preset: str = "Plate_A1_D1"
    plate_format: str = "96-well (8 × 12)"

    image_field_width_mm: float = 2.425
    image_field_height_mm: float = 1.94
    crystal_marker_diameter_px: int = 16
    crystal_marker_colour: str = "#FFFF00"

    first_drop_x_mm: float = 1.38
    first_drop_y_mm: float = 2.07
    drop_step_x_mm: float = 2.425
    drop_step_y_mm: float = 1.94

    drop_width_px: int = 240
    image_gap_px: int = 1
    well_gap_px: int = 2
    outer_margin_px: int = 45
    background_hex: str = "#FFFFFF"
    show_well_labels: bool = True
    show_missing: bool = True

    input_folder: str = ""
    output_folder: str = ""

    @property
    def row_values(self) -> list[str]:
        return split_labels(self.row_labels, self.rows, "Row")

    @property
    def column_values(self) -> list[str]:
        return split_labels(self.column_labels, self.columns, "Column")

    def validate(self) -> None:
        if self.rows < 1 or self.columns < 1:
            raise ValueError("The overall grid must have at least one row and one column.")
        if self.drops_per_well < 1:
            raise ValueError("Drops per well must be at least 1.")
        if self.drop_rows * self.drop_columns < self.drops_per_well:
            raise ValueError("Drop rows × drop columns must be at least the number of drops per well.")
        if self.image_field_width_mm <= 0 or self.image_field_height_mm <= 0:
            raise ValueError("Crystal locator field width and height must be greater than zero.")
        if self.crystal_marker_diameter_px < 2:
            raise ValueError("Crystal marker diameter must be at least 2 pixels.")
        re.compile(self.filename_regex)
        _ = self.row_values
        _ = self.column_values


@dataclass
class ImageRecord:
    path: Path
    plate: str
    well: str
    drop: int


@dataclass
class Crystal:
    plate: str
    well: str
    drop: int
    x_mm: float
    y_mm: float
    fx: float
    fy: float
    note: str
    image_file: str


def load_config() -> AppConfig:
    current_path = app_data_dir() / CONFIG_FILENAME
    legacy_candidates = [
        app_data_dir() / LEGACY_CONFIG_FILENAME,
        (Path(os.environ.get("APPDATA", Path.home())) / "WellPlateImageCollator" / LEGACY_CONFIG_FILENAME)
        if sys.platform.startswith("win")
        else (Path.home() / ".config" / "WellPlateImageCollator" / LEGACY_CONFIG_FILENAME),
    ]
    path = current_path if current_path.exists() else next((p for p in legacy_candidates if p.exists()), current_path)
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        allowed = AppConfig.__dataclass_fields__.keys()
        config = AppConfig(**{key: value for key, value in data.items() if key in allowed})
        if not config.filename_presets:
            config.filename_presets = {}
        return config
    except Exception:
        return AppConfig()

def save_config(config: AppConfig) -> None:
    (app_data_dir() / CONFIG_FILENAME).write_text(
        json.dumps(asdict(config), indent=2), encoding="utf-8"
    )


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = ["arialbd.ttf" if bold else "arial.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


def parse_filename(path: Path, config: AppConfig) -> Optional[ImageRecord]:
    match = re.fullmatch(config.filename_regex, path.stem, flags=re.IGNORECASE)
    if not match:
        return None
    groups = match.groupdict()
    well = groups.get("well")
    if not well and groups.get("row") and groups.get("column"):
        well = f"{groups['row']}{groups['column']}"
    if not well:
        raise ValueError("The filename expression must provide either 'well', or both 'row' and 'column'.")
    plate = groups.get("plate") or config.default_plate_name
    drop_text = groups.get("drop") or "1"
    return ImageRecord(path=path, plate=plate, well=well, drop=int(drop_text))


def scan_folder(folder: Path, config: AppConfig):
    grouped: dict[str, dict[tuple[str, int], ImageRecord]] = {}
    invalid: list[str] = []
    duplicates: list[str] = []
    valid_wells = {f"{r}{c}" for r in config.row_values for c in config.column_values}

    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            record = parse_filename(path, config)
        except Exception as exc:
            invalid.append(f"{path.name}: {exc}")
            continue
        if record is None:
            invalid.append(path.name)
            continue
        if record.well not in valid_wells or not (1 <= record.drop <= config.drops_per_well):
            invalid.append(path.name)
            continue
        key = (record.well, record.drop)
        plate_map = grouped.setdefault(record.plate, {})
        if key in plate_map:
            duplicates.append(f"{path.name} conflicts with {plate_map[key].path.name}")
        else:
            plate_map[key] = record
    return grouped, invalid, duplicates


def image_aspect(folder: Path, grouped) -> float:
    for records in grouped.values():
        for record in records.values():
            try:
                with Image.open(record.path) as image:
                    return image.width / image.height
            except Exception:
                pass
    return 4 / 3


def resize_no_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    image = image.convert("RGB")
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return canvas


def drop_centre(config: AppConfig, well: str, drop: int) -> tuple[float, float]:
    row_labels, col_labels = config.row_values, config.column_values
    row = next((i for i, value in enumerate(row_labels) if well.startswith(value)), None)
    if row is None:
        raise ValueError(f"Unknown well {well}")
    column_text = well[len(row_labels[row]):]
    column = col_labels.index(column_text)
    drop_index = drop - 1
    dr, dc = divmod(drop_index, config.drop_columns)
    return (
        config.first_drop_x_mm + column * config.well_pitch_x_mm + dc * config.drop_step_x_mm,
        config.first_drop_y_mm + row * config.well_pitch_y_mm + dr * config.drop_step_y_mm,
    )


def render_plate(plate: str, records, config: AppConfig, aspect: float) -> tuple[Image.Image, list[tuple[str, int]]]:
    drop_w = config.drop_width_px
    drop_h = max(1, round(drop_w / aspect))
    well_w = config.drop_columns * drop_w + (config.drop_columns - 1) * config.image_gap_px
    well_h = config.drop_rows * drop_h + (config.drop_rows - 1) * config.image_gap_px

    label_left = 48
    label_top = 48
    grid_w = config.columns * well_w + (config.columns - 1) * config.well_gap_px
    grid_h = config.rows * well_h + (config.rows - 1) * config.well_gap_px
    width = config.outer_margin_px * 2 + label_left + grid_w
    height = config.outer_margin_px * 2 + label_top + grid_h

    canvas = Image.new("RGB", (width, height), config.background_hex)
    draw = ImageDraw.Draw(canvas)
    f_label = font(max(14, min(30, drop_w // 7)), bold=True)
    f_missing = font(max(10, drop_w // 12), bold=True)

    gx = config.outer_margin_px + label_left
    gy = config.outer_margin_px + label_top

    for ci, col_label in enumerate(config.column_values):
        x = gx + ci * (well_w + config.well_gap_px) + well_w / 2
        draw.text((x, config.outer_margin_px + label_top / 2), col_label, fill="black", font=f_label, anchor="mm")
    for ri, row_label in enumerate(config.row_values):
        y = gy + ri * (well_h + config.well_gap_px) + well_h / 2
        draw.text((config.outer_margin_px + label_left / 2, y), row_label, fill="black", font=f_label, anchor="mm")

    missing: list[tuple[str, int]] = []
    for ri, row_label in enumerate(config.row_values):
        for ci, col_label in enumerate(config.column_values):
            well = f"{row_label}{col_label}"
            wx = gx + ci * (well_w + config.well_gap_px)
            wy = gy + ri * (well_h + config.well_gap_px)

            for drop in range(1, config.drops_per_well + 1):
                index = drop - 1
                dr, dc = divmod(index, config.drop_columns)
                x = wx + dc * (drop_w + config.image_gap_px)
                y = wy + dr * (drop_h + config.image_gap_px)
                record = records.get((well, drop))
                if record:
                    try:
                        with Image.open(record.path) as source:
                            fitted = resize_no_crop(source, drop_w, drop_h)
                        canvas.paste(fitted, (x, y))
                    except Exception:
                        record = None
                if not record:
                    missing.append((well, drop))
                    if config.show_missing:
                        draw.rectangle((x, y, x + drop_w - 1, y + drop_h - 1), outline="#CC0000", width=2)
                        draw.text((x + drop_w / 2, y + drop_h / 2), f"Missing\n{config.drop_prefix}{drop}",
                                  fill="#CC0000", font=f_missing, anchor="mm", align="center")
                draw.rectangle((x, y, x + drop_w - 1, y + drop_h - 1), outline="#333333", width=1)

            draw.rectangle((wx, wy, wx + well_w - 1, wy + well_h - 1), outline="black", width=2)
            if config.show_well_labels:
                draw.rectangle((wx + 3, wy + 3, wx + 48, wy + 24), fill="white", outline="black")
                draw.text((wx + 25, wy + 13), well, fill="black", font=font(12, True), anchor="mm")

    draw.rectangle((gx - 2, gy - 2, gx + grid_w + 1, gy + grid_h + 1), outline="black", width=4)
    title = f"{plate} — {config.rows}×{config.columns}, {config.drops_per_well} image(s) per well"
    draw.text((width / 2, 12), title, fill="black", font=font(20, True), anchor="ma")
    return canvas, missing


class CrystalLocator:
    def __init__(self, parent: tk.Tk, folder: Path, config: AppConfig):
        self.config = config
        self.folder = folder
        self.grouped, _, _ = scan_folder(folder, config)
        if not self.grouped:
            raise ValueError("No matching images were found.")

        self.window = tk.Toplevel(parent)
        self.window.title(f"{APP_NAME} — Crystal Locator")
        self.window.geometry("1450x850")
        try:
            self.window.iconbitmap(str(resource_path("crystalatlas_icon.ico")))
        except Exception:
            pass

        self.crystals_path = folder / "Crystal_Locations.csv"
        self.crystals: list[Crystal] = []
        self.current: Optional[ImageRecord] = None
        self.source: Optional[Image.Image] = None
        self.photo = None
        self.zoom = 1.0
        self.origin = [0.0, 0.0]
        self.pan_anchor = None

        self.plate_var = tk.StringVar()
        self.well_var = tk.StringVar(value=f"{config.row_values[0]}{config.column_values[0]}")
        self.drop_var = tk.IntVar(value=1)
        self.note_var = tk.StringVar()
        self.coord_var = tk.StringVar(value="Hover over the image to show coordinates.")
        self.field_w_var = tk.DoubleVar(value=config.image_field_width_mm)
        self.marker_size_var = tk.IntVar(value=config.crystal_marker_diameter_px)
        self.marker_colour_var = tk.StringVar(value=config.crystal_marker_colour)

        self._build()
        self.window.bind("<Left>", lambda event: self.change_image(-1))
        self.window.bind("<Right>", lambda event: self.change_image(1))
        self._load_crystals()
        plates = sorted(self.grouped)
        self.plate_combo["values"] = plates
        self.plate_var.set(plates[0])
        self.load_image()

    def _build(self):
        selector = ttk.Frame(self.window, padding=8)
        selector.pack(fill="x")
        ttk.Label(selector, text="Plate").pack(side="left")
        self.plate_combo = ttk.Combobox(selector, textvariable=self.plate_var, state="readonly", width=22)
        self.plate_combo.pack(side="left", padx=4)
        ttk.Label(selector, text="Well").pack(side="left", padx=(10, 0))
        wells = [f"{r}{c}" for r in self.config.row_values for c in self.config.column_values]
        self.well_combo = ttk.Combobox(selector, textvariable=self.well_var, values=wells, state="readonly", width=10)
        self.well_combo.pack(side="left", padx=4)
        ttk.Label(selector, text="Drop").pack(side="left", padx=(10, 0))
        self.drop_combo = ttk.Combobox(selector, textvariable=self.drop_var,
                                       values=list(range(1, self.config.drops_per_well + 1)),
                                       state="readonly", width=5)
        self.drop_combo.pack(side="left", padx=4)
        ttk.Button(selector, text="Previous", command=lambda: self.change_image(-1)).pack(side="left", padx=(5, 2))
        ttk.Button(selector, text="Next", command=lambda: self.change_image(1)).pack(side="left", padx=2)
        ttk.Button(selector, text="Load", command=self.load_image).pack(side="left", padx=2)
        ttk.Button(selector, text="Fit", command=self.fit).pack(side="left", padx=2)

        ttk.Label(selector, text="Field width (mm)").pack(side="left", padx=(20, 3))
        ttk.Entry(selector, textvariable=self.field_w_var, width=8).pack(side="left")
        ttk.Button(selector, text="Apply size", command=self.apply_field_size).pack(side="left", padx=5)
        ttk.Label(selector, text="Marker size").pack(side="left", padx=(18, 3))
        ttk.Spinbox(selector, from_=2, to=200, textvariable=self.marker_size_var, width=6).pack(side="left")
        ttk.Button(selector, text="Marker colour", command=self.choose_marker_colour).pack(side="left", padx=5)
        self.marker_colour_swatch = tk.Label(selector, width=3, relief="sunken", background=self.config.crystal_marker_colour)
        self.marker_colour_swatch.pack(side="left", padx=(0, 5))
        ttk.Button(selector, text="Apply marker", command=self.apply_marker_settings).pack(side="left")

        body = ttk.Panedwindow(self.window, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        left = ttk.Frame(body)
        right = ttk.Frame(body, width=430)
        body.add(left, weight=4)
        body.add(right, weight=2)

        self.canvas = tk.Canvas(left, bg="#222222")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Motion>", self.motion)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<ButtonPress-3>", self.pan_start)
        self.canvas.bind("<B3-Motion>", self.pan_move)

        ttk.Label(right, text="Selected crystals", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        columns = ("plate", "well", "drop", "x", "y", "note")
        self.tree = ttk.Treeview(right, columns=columns, show="headings", selectmode="browse")
        widths = {"plate": 85, "well": 55, "drop": 45, "x": 70, "y": 70, "note": 150}
        for key in columns:
            self.tree.heading(key, text=key.title())
            self.tree.column(key, width=widths[key], stretch=(key == "note"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.jump_to_selected)

        note_frame = ttk.Frame(right)
        note_frame.pack(fill="x", pady=6)
        ttk.Label(note_frame, text="New marker note").pack(anchor="w")
        ttk.Entry(note_frame, textvariable=self.note_var).pack(fill="x")
        controls = ttk.Frame(right)
        controls.pack(fill="x")
        ttk.Button(controls, text="Delete selected", command=self.delete_selected).pack(side="left")
        ttk.Button(controls, text="Save CSV", command=self.save_crystals).pack(side="left", padx=5)
        ttk.Button(controls, text="Open CSV", command=self.open_csv).pack(side="left")

        ttk.Label(self.window, textvariable=self.coord_var, padding=8).pack(fill="x")

    def apply_field_size(self):
        try:
            width = float(self.field_w_var.get())
            if width <= 0:
                raise ValueError

            self.config.image_field_width_mm = width

            if self.source is not None and self.source.width > 0:
                self.config.image_field_height_mm = (
                    width * self.source.height / self.source.width
                )

            save_config(self.config)
            self.coord_var.set(
                f"Crystal locator field set to "
                f"{self.config.image_field_width_mm:g} × "
                f"{self.config.image_field_height_mm:g} mm "
                f"(height calculated automatically)."
            )
        except (TypeError, ValueError):
            messagebox.showerror(
                "Field size",
                "Enter a positive numeric field width.",
                parent=self.window,
            )

    def choose_marker_colour(self):
        chosen = colorchooser.askcolor(self.marker_colour_var.get(), parent=self.window)[1]
        if chosen:
            self.marker_colour_var.set(chosen)
            self.marker_colour_swatch.configure(background=chosen)

    def apply_marker_settings(self):
        try:
            diameter = int(self.marker_size_var.get())
            if diameter < 2:
                raise ValueError
            colour = self.marker_colour_var.get().strip()
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", colour):
                raise ValueError
            self.config.crystal_marker_diameter_px = diameter
            self.config.crystal_marker_colour = colour
            save_config(self.config)
            self.marker_colour_swatch.configure(background=colour)
            self.redraw()
            self.coord_var.set(f"Crystal marker set to {diameter}px, colour {colour}.")
        except Exception:
            messagebox.showerror(
                "Crystal marker",
                "Enter a marker diameter of at least 2 pixels and choose a valid colour.",
                parent=self.window,
            )

    def change_image(self, direction: int):
        image_records = []

        for plate_name in sorted(self.grouped):
            plate_records = self.grouped[plate_name]

            for row_label in self.config.row_values:
                for column_label in self.config.column_values:
                    well = f"{row_label}{column_label}"

                    for drop in range(1, self.config.drops_per_well + 1):
                        record = plate_records.get((well, drop))
                        if record is not None:
                            image_records.append(record)

        if not image_records:
            return

        current_key = (
            self.plate_var.get(),
            self.well_var.get(),
            int(self.drop_var.get()),
        )

        current_index = next(
            (
                index
                for index, record in enumerate(image_records)
                if (record.plate, record.well, record.drop) == current_key
            ),
            0,
        )

        new_index = (current_index + direction) % len(image_records)
        new_record = image_records[new_index]

        self.plate_var.set(new_record.plate)
        self.well_var.set(new_record.well)
        self.drop_var.set(new_record.drop)
        self.load_image()

    def load_image(self):
        record = self.grouped.get(self.plate_var.get(), {}).get((self.well_var.get(), int(self.drop_var.get())))
        self.current = record
        if not record:
            self.source = None
            self.redraw()
            return
        with Image.open(record.path) as image:
            self.source = image.convert("RGB")

        if self.source.width > 0:
            self.config.image_field_height_mm = (
                self.config.image_field_width_mm
                * self.source.height
                / self.source.width
            )

        self.fit()

    def fit(self):
        if not self.source:
            return
        self.zoom = min(max(100, self.canvas.winfo_width()) / self.source.width,
                        max(100, self.canvas.winfo_height()) / self.source.height) * .96
        self.origin = [(self.canvas.winfo_width() - self.source.width * self.zoom) / 2,
                       (self.canvas.winfo_height() - self.source.height * self.zoom) / 2]
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        if not self.source:
            self.canvas.create_text(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2,
                                    text="No image for selected position", fill="white", font=("TkDefaultFont", 16))
            return
        w, h = max(1, round(self.source.width*self.zoom)), max(1, round(self.source.height*self.zoom))
        shown = self.source.resize((w, h), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(shown)
        self.canvas.create_image(self.origin[0], self.origin[1], image=self.photo, anchor="nw")
        for index, crystal in enumerate(self.current_crystals(), 1):
            x = self.origin[0] + crystal.fx*w
            y = self.origin[1] + crystal.fy*h
            radius = max(1, self.config.crystal_marker_diameter_px / 2)
            colour = self.config.crystal_marker_colour
            self.canvas.create_oval(x-radius, y-radius, x+radius, y+radius, outline=colour, width=2)
            self.canvas.create_text(x+radius+4, y-radius-2, text=str(index), fill=colour, anchor="sw")

    def fraction(self, x, y):
        if not self.source:
            return None
        w, h = self.source.width*self.zoom, self.source.height*self.zoom
        fx, fy = (x-self.origin[0])/w, (y-self.origin[1])/h
        return (fx, fy) if 0 <= fx <= 1 and 0 <= fy <= 1 else None

    def xy_mm(self, fx, fy):
        cx, cy = drop_centre(self.config, self.current.well, self.current.drop)
        return (cx + (fx-.5)*self.config.image_field_width_mm,
                cy + (fy-.5)*self.config.image_field_height_mm)

    def motion(self, event):
        p = self.fraction(event.x, event.y)
        if not p or not self.current:
            return
        x, y = self.xy_mm(*p)
        self.coord_var.set(f"{self.current.plate}  {self.current.well}  {self.config.drop_prefix}{self.current.drop}"
                           f"    X {x:.4f} mm    Y {y:.4f} mm    image {p[0]*100:.1f}%, {p[1]*100:.1f}%")

    def click(self, event):
        p = self.fraction(event.x, event.y)
        if not p or not self.current:
            return
        x, y = self.xy_mm(*p)
        self.crystals.append(Crystal(self.current.plate, self.current.well, self.current.drop,
                                     x, y, p[0], p[1], self.note_var.get().strip(), self.current.path.name))
        self.note_var.set("")
        self.save_crystals(silent=True)
        self.refresh_tree()
        self.redraw()
        self.window.clipboard_clear()
        self.window.clipboard_append(f"{x:.4f}, {y:.4f}")

    def current_crystals(self):
        if not self.current:
            return []
        return [c for c in self.crystals if (c.plate, c.well, c.drop) ==
                (self.current.plate, self.current.well, self.current.drop)]

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.crystals):
            self.tree.insert("", "end", iid=str(i), values=(c.plate, c.well, c.drop,
                                                             f"{c.x_mm:.4f}", f"{c.y_mm:.4f}", c.note))

    def jump_to_selected(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        c = self.crystals[int(selection[0])]
        self.plate_var.set(c.plate)
        self.well_var.set(c.well)
        self.drop_var.set(c.drop)
        self.load_image()

    def delete_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        del self.crystals[int(selection[0])]
        self.save_crystals(silent=True)
        self.refresh_tree()
        self.redraw()

    def wheel(self, event):
        if not self.source:
            return
        factor = 1.15 if event.delta > 0 else 1/1.15
        old = self.zoom
        new = max(.05, min(20, old*factor))
        ix, iy = (event.x-self.origin[0])/old, (event.y-self.origin[1])/old
        self.zoom = new
        self.origin = [event.x-ix*new, event.y-iy*new]
        self.redraw()

    def pan_start(self, event):
        self.pan_anchor = (event.x, event.y)

    def pan_move(self, event):
        if not self.pan_anchor:
            return
        self.origin[0] += event.x-self.pan_anchor[0]
        self.origin[1] += event.y-self.pan_anchor[1]
        self.pan_anchor = (event.x, event.y)
        self.redraw()

    def _load_crystals(self):
        if self.crystals_path.exists():
            try:
                with self.crystals_path.open(newline="", encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        self.crystals.append(Crystal(
                            row["Plate"], row["Well"], int(row["Drop"]),
                            float(row["X_mm"]), float(row["Y_mm"]),
                            float(row["Image_X_Fraction"]), float(row["Image_Y_Fraction"]),
                            row.get("Note", ""), row.get("Image_File", "")
                        ))
            except Exception as exc:
                messagebox.showwarning("Crystal list", f"Could not load existing list:\n{exc}", parent=self.window)
        self.refresh_tree()

    def save_crystals(self, silent=False):
        with self.crystals_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Plate","Well","Drop","X_mm","Y_mm","Image_X_Fraction","Image_Y_Fraction","Note","Image_File"])
            for c in self.crystals:
                writer.writerow([c.plate,c.well,c.drop,f"{c.x_mm:.6f}",f"{c.y_mm:.6f}",
                                 f"{c.fx:.8f}",f"{c.fy:.8f}",c.note,c.image_file])
        if not silent:
            messagebox.showinfo("Crystal list", f"Saved {len(self.crystals)} crystals.", parent=self.window)

    def open_csv(self):
        self.save_crystals(silent=True)
        os.startfile(self.crystals_path) if sys.platform.startswith("win") else None


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = load_config()
        root.title(APP_NAME)
        root.geometry("1040x780")
        try:
            root.iconbitmap(str(resource_path("crystalatlas_icon.ico")))
        except Exception:
            pass

        self.vars = {}
        self.status = tk.StringVar(value="Ready.")
        self.preview_photo = None
        self.last_grouped = {}

        self._build()
        self.load_vars()

    def add_entry(self, parent, label, key, row, width=18):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.StringVar()
        self.vars[key] = var
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="ew", pady=3)

    def _build(self):
        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(main, width=440)
        right = ttk.Frame(main)
        main.add(left, weight=2)
        main.add(right, weight=3)

        notebook = ttk.Notebook(left)
        notebook.pack(fill="both", expand=True)

        io = ttk.Frame(notebook, padding=10)
        grid = ttk.Frame(notebook, padding=10)
        names = ttk.Frame(notebook, padding=10)
        coord = ttk.Frame(notebook, padding=10)
        notebook.add(io, text="Folders / Output")
        notebook.add(grid, text="Grid / Drops")
        notebook.add(names, text="Filenames")
        notebook.add(coord, text="Coordinates")

        io.columnconfigure(1, weight=1)
        self.add_entry(io, "Input folder", "input_folder", 0, 34)
        ttk.Button(io, text="Browse", command=self.browse_input).grid(row=0, column=2, padx=4)
        self.add_entry(io, "Output folder", "output_folder", 1, 34)
        ttk.Button(io, text="Browse", command=self.browse_output).grid(row=1, column=2, padx=4)
        self.add_entry(io, "Drop image width (px)", "drop_width_px", 2)
        self.add_entry(io, "Gap between images (px)", "image_gap_px", 3)
        self.add_entry(io, "Gap between wells (px)", "well_gap_px", 4)
        self.add_entry(io, "Outer margin (px)", "outer_margin_px", 5)
        ttk.Button(io, text="Choose background", command=self.choose_colour).grid(row=6, column=0, sticky="w", pady=6)
        self.colour_label = ttk.Label(io, text="")
        self.colour_label.grid(row=6, column=1, sticky="w")
        self.show_labels_var = tk.BooleanVar()
        self.show_missing_var = tk.BooleanVar()
        ttk.Checkbutton(io, text="Show well labels", variable=self.show_labels_var).grid(row=7,column=0,columnspan=2,sticky="w")
        ttk.Checkbutton(io, text="Show missing positions", variable=self.show_missing_var).grid(row=8,column=0,columnspan=2,sticky="w")

        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="Plate format").grid(row=0, column=0, sticky="w", pady=3)
        self.plate_format_var = tk.StringVar()
        self.plate_format_combo = ttk.Combobox(
            grid, textvariable=self.plate_format_var,
            values=list(PLATE_FORMATS), state="readonly", width=28
        )
        self.plate_format_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self.plate_format_combo.bind("<<ComboboxSelected>>", self.apply_plate_format)
        ttk.Label(grid, text="Choose Custom to edit the row and column counts manually.",
                  wraplength=390).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        fields = [
            ("Overall rows", "rows"), ("Overall columns", "columns"),
            ("Row labels, comma-separated (blank = A, B...)", "row_labels"),
            ("Column labels, comma-separated (blank = 1, 2...)", "column_labels"),
            ("Drops/images per well", "drops_per_well"),
            ("Drop layout columns", "drop_columns"), ("Drop layout rows", "drop_rows"),
            ("Drop filename prefix", "drop_prefix"),
            ("Well pitch X (mm)", "well_pitch_x_mm"), ("Well pitch Y (mm)", "well_pitch_y_mm")
        ]
        for i,(label,key) in enumerate(fields):
            self.add_entry(grid,label,key,i + 2,30)

        names.columnconfigure(1, weight=1)
        ttk.Label(names, text="Regular expression with named groups: plate, well, drop\n"
                              "Alternatively use row and column instead of well.",
                  wraplength=390).grid(row=0,column=0,columnspan=3,sticky="w")

        ttk.Label(names, text="Filename preset").grid(row=1, column=0, sticky="w", pady=3)
        self.filename_preset_var = tk.StringVar()
        self.filename_preset_combo = ttk.Combobox(names, textvariable=self.filename_preset_var,
                                                   state="readonly", width=30)
        self.filename_preset_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
        self.filename_preset_combo.bind("<<ComboboxSelected>>", self.load_filename_preset)

        self.add_entry(names, "Filename expression", "filename_regex", 2, 42)
        self.add_entry(names, "Default plate name", "default_plate_name", 3, 28)

        preset_buttons = ttk.Frame(names)
        preset_buttons.grid(row=4, column=0, columnspan=3, sticky="ew", pady=5)
        ttk.Button(preset_buttons, text="New preset", command=self.new_filename_preset).pack(side="left")
        ttk.Button(preset_buttons, text="Save / Update", command=self.save_filename_preset).pack(side="left", padx=4)
        ttk.Button(preset_buttons, text="Delete", command=self.delete_filename_preset).pack(side="left")

        self.test_name_var = tk.StringVar(value="Tester1_A1_D1.jpg")
        ttk.Label(names,text="Test filename").grid(row=5,column=0,sticky="w")
        ttk.Entry(names,textvariable=self.test_name_var).grid(row=5,column=1,columnspan=2,sticky="ew")
        ttk.Button(names,text="Test expression",command=self.test_filename).grid(row=6,column=0,sticky="w",pady=5)
        self.test_result = ttk.Label(names,text="")
        self.test_result.grid(row=7,column=0,columnspan=3,sticky="w")

        coord.columnconfigure(1, weight=1)
        coord_fields = [
            ("Crystal locator field width (mm)", "image_field_width_mm"),
            ("Crystal marker diameter (px)", "crystal_marker_diameter_px"),
            ("Crystal marker colour (#RRGGBB)", "crystal_marker_colour"),
            ("First drop centre X (mm)", "first_drop_x_mm"),
            ("First drop centre Y (mm)", "first_drop_y_mm"),
            ("Drop centre step X (mm)", "drop_step_x_mm"),
            ("Drop centre step Y (mm)", "drop_step_y_mm"),
        ]
        for i,(label,key) in enumerate(coord_fields):
            self.add_entry(coord,label,key,i,22)
        ttk.Label(coord, text="Set the locator field width here. Field height is calculated automatically from each image aspect ratio. The width can also be changed live inside the locator window.",
                  wraplength=390).grid(row=8,column=0,columnspan=2,sticky="w",pady=8)

        controls = ttk.Frame(left)
        controls.pack(fill="x", pady=8)
        ttk.Button(controls,text="Save settings",command=self.save_settings).pack(side="left")
        ttk.Button(controls,text="Scan / Preview",command=self.scan_preview).pack(side="left",padx=5)
        ttk.Button(controls,text="Generate PNGs",command=self.generate).pack(side="left",padx=5)
        ttk.Button(controls,text="Crystal locator",command=self.open_locator).pack(side="left")

        self.preview = ttk.Label(right, anchor="center")
        self.preview.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(right, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(6, 2))
        ttk.Label(right,textvariable=self.status).pack(fill="x")

    def load_vars(self):
        for key,var in self.vars.items():
            var.set(str(getattr(self.config,key)))
        self.show_labels_var.set(self.config.show_well_labels)
        self.show_missing_var.set(self.config.show_missing)
        self.colour_label.config(text=self.config.background_hex)
        self.plate_format_var.set(self.config.plate_format if self.config.plate_format in PLATE_FORMATS else "Custom")
        self.refresh_filename_presets()
        selected = self.config.selected_filename_preset
        if selected in self.all_filename_presets():
            self.filename_preset_var.set(selected)
        elif self.filename_preset_combo["values"]:
            self.filename_preset_var.set(self.filename_preset_combo["values"][0])

    def collect(self):
        c = AppConfig()
        integer_keys = {"rows","columns","drops_per_well","drop_columns","drop_rows",
                        "drop_width_px","image_gap_px","well_gap_px","outer_margin_px","crystal_marker_diameter_px"}
        float_keys = {"well_pitch_x_mm","well_pitch_y_mm","image_field_width_mm","image_field_height_mm",
                      "first_drop_x_mm","first_drop_y_mm","drop_step_x_mm","drop_step_y_mm"}
        for key,var in self.vars.items():
            value = var.get().strip()
            setattr(c,key,int(value) if key in integer_keys else float(value) if key in float_keys else value)
        c.background_hex = self.config.background_hex
        c.filename_presets = dict(self.config.filename_presets)
        c.selected_filename_preset = self.filename_preset_var.get() or self.config.selected_filename_preset
        c.plate_format = self.plate_format_var.get() or "Custom"
        c.show_well_labels = self.show_labels_var.get()
        c.show_missing = self.show_missing_var.get()
        chosen = PLATE_FORMATS.get(c.plate_format)
        if chosen is not None and chosen != (c.rows, c.columns):
            c.plate_format = "Custom"
            self.plate_format_var.set("Custom")
        c.validate()
        return c

    def save_settings(self):
        try:
            self.config = self.collect()
            save_config(self.config)
            self.status.set("Settings saved.")
        except Exception as exc:
            messagebox.showerror("Settings", str(exc))

    def browse_input(self):
        path = filedialog.askdirectory()
        if path:
            self.vars["input_folder"].set(path)
            if not self.vars["output_folder"].get():
                self.vars["output_folder"].set(str(Path(path)/"Collated_Output"))

    def browse_output(self):
        path = filedialog.askdirectory()
        if path: self.vars["output_folder"].set(path)

    def choose_colour(self):
        chosen = colorchooser.askcolor(self.config.background_hex)[1]
        if chosen:
            self.config.background_hex = chosen
            self.colour_label.config(text=chosen)

    def all_filename_presets(self) -> dict[str, str]:
        presets = dict(BUILTIN_FILENAME_PRESETS)
        presets.update(self.config.filename_presets)
        return presets

    def refresh_filename_presets(self):
        names = sorted(self.all_filename_presets(), key=str.lower)
        self.filename_preset_combo["values"] = names

    def load_filename_preset(self, event=None):
        name = self.filename_preset_var.get()
        expression = self.all_filename_presets().get(name)
        if expression:
            self.vars["filename_regex"].set(expression)
            self.config.selected_filename_preset = name

    def new_filename_preset(self):
        name = simpledialog.askstring("New filename preset", "Enter a name for the preset:", parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in BUILTIN_FILENAME_PRESETS:
            messagebox.showerror("Filename preset", "That name is reserved for a built-in preset.")
            return
        self.filename_preset_var.set(name)
        self.save_filename_preset()

    def save_filename_preset(self):
        name = self.filename_preset_var.get().strip()
        expression = self.vars["filename_regex"].get().strip()
        if not name:
            name = simpledialog.askstring("Save filename preset", "Enter a name for the preset:", parent=self.root)
            if not name:
                return
            name = name.strip()
        if name in BUILTIN_FILENAME_PRESETS:
            messagebox.showinfo("Filename preset", "Built-in presets cannot be overwritten. Use New preset to create your own copy.")
            return
        try:
            re.compile(expression)
            test_config = self.collect()
            test_config.filename_regex = expression
            test_config.filename_presets[name] = expression
            test_config.selected_filename_preset = name
            self.config = test_config
            save_config(self.config)
            self.refresh_filename_presets()
            self.filename_preset_var.set(name)
            self.status.set(f"Filename preset saved: {name}")
        except Exception as exc:
            messagebox.showerror("Filename preset", str(exc))

    def delete_filename_preset(self):
        name = self.filename_preset_var.get()
        if name in BUILTIN_FILENAME_PRESETS:
            messagebox.showinfo("Filename preset", "Built-in presets cannot be deleted.")
            return
        if name not in self.config.filename_presets:
            return
        if not messagebox.askyesno("Delete filename preset", f"Delete preset '{name}'?"):
            return
        del self.config.filename_presets[name]
        self.config.selected_filename_preset = "Plate_A1_D1"
        save_config(self.config)
        self.refresh_filename_presets()
        self.filename_preset_var.set("Plate_A1_D1")
        self.load_filename_preset()

    def apply_plate_format(self, event=None):
        name = self.plate_format_var.get()
        dimensions = PLATE_FORMATS.get(name)
        if dimensions is None:
            return
        rows, columns = dimensions
        self.vars["rows"].set(str(rows))
        self.vars["columns"].set(str(columns))
        self.vars["row_labels"].set("")
        self.vars["column_labels"].set("")
        self.config.plate_format = name
        self.status.set(f"Applied {name} format.")

    def test_filename(self):
        try:
            c = self.collect()
            path = Path(self.test_name_var.get())
            record = parse_filename(path, c)
            self.test_result.config(text=(f"Plate={record.plate}, well={record.well}, drop={record.drop}"
                                          if record else "No match"))
        except Exception as exc:
            self.test_result.config(text=f"Error: {exc}")

    def set_progress(self, value: float, text: str | None = None):
        self.progress["value"] = max(0, min(100, value))
        if text is not None:
            self.status.set(text)
        self.root.update_idletasks()

    def scan_preview(self):
        try:
            self.set_progress(0, "Reading settings...")
            self.config = self.collect()
            folder = Path(self.config.input_folder)
            if not folder.is_dir(): raise ValueError("Select a valid input folder.")
            self.set_progress(20, "Scanning image folder...")
            grouped, invalid, duplicates = scan_folder(folder,self.config)
            if not grouped: raise ValueError("No matching images found.")
            self.last_grouped = grouped
            plate = sorted(grouped)[0]
            aspect = image_aspect(folder,grouped)
            self.set_progress(55, f"Rendering preview for {plate}...")
            image,_ = render_plate(plate,grouped[plate],self.config,aspect)
            maxw,maxh = max(300,self.preview.winfo_width()),max(300,self.preview.winfo_height())
            image.thumbnail((maxw,maxh),Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(image)
            self.preview.config(image=self.preview_photo)
            self.set_progress(100, f"{len(grouped)} plate(s); {len(invalid)} invalid; {len(duplicates)} duplicate(s).")
            save_config(self.config)
        except Exception as exc:
            self.set_progress(0, "Preview failed.")
            messagebox.showerror("Preview",str(exc))

    def generate(self):
        try:
            self.set_progress(0, "Reading settings...")
            self.config = self.collect()
            folder = Path(self.config.input_folder)
            output = Path(self.config.output_folder or folder/"Collated_Output")
            output.mkdir(parents=True,exist_ok=True)
            self.set_progress(10, "Scanning image folder...")
            grouped,invalid,duplicates = scan_folder(folder,self.config)
            if not grouped: raise ValueError("No matching images found.")
            aspect = image_aspect(folder,grouped)
            report=[]
            items = list(grouped.items())
            total = len(items)
            for index, (plate, records) in enumerate(items, start=1):
                self.set_progress(10 + ((index - 1) / max(1, total)) * 80, f"Rendering plate {index} of {total}: {plate}")
                image,missing = render_plate(plate,records,self.config,aspect)
                safe = re.sub(r'[<>:"/\\|?*]+',"_",plate)
                image.save(output/f"{safe}_CrystalAtlas.png")
                report.extend(["Missing",plate,well,drop,""] for well,drop in missing)
            report.extend(["Invalid","","","",name] for name in invalid)
            report.extend(["Duplicate","","","",name] for name in duplicates)
            with (output/"CrystalAtlas_Report.csv").open("w",newline="",encoding="utf-8-sig") as f:
                w=csv.writer(f); w.writerow(["Type","Plate","Well","Drop","File"]); w.writerows(report)
            save_config(self.config)
            self.set_progress(100, f"Complete: created {len(grouped)} layout(s).")
            messagebox.showinfo("Complete",f"Created {len(grouped)} layout(s) in:\n{output}")
        except Exception as exc:
            self.set_progress(0, "Generation failed.")
            messagebox.showerror("Generate",str(exc))

    def open_locator(self):
        try:
            self.config=self.collect()
            folder=Path(self.config.input_folder)
            if not folder.is_dir(): raise ValueError("Select a valid input folder.")
            CrystalLocator(self.root,folder,self.config)
            save_config(self.config)
        except Exception as exc:
            messagebox.showerror("Crystal locator",str(exc))


def main():
    root=tk.Tk()
    App(root)
    root.mainloop()


if __name__=="__main__":
    main()
