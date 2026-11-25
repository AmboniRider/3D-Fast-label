"""
Generatore 3D per etichette/targhette multi-colore basato sui modelli STEP di riferimento:
- pill: targhetta verticale a pillola (default 25 x 75 mm, spessore 1.8 mm) con foro superiore e testo verticale.
- rectangular: targhetta rettangolare arrotondata orizzontale (default 80 x 50 mm, spessore 1.6 mm) con foro in alto a sinistra e testo orizzontale.
- round: targhetta circolare (default Ø 35 mm, spessore 1.6 mm) con foro superiore, bordino opzionale e testo orizzontale.

Caratteristiche principali:
- Geometrie parametriche fedeli ai file STEP in modelli/ con smussi 0.2 mm x 45° su entrambe le facce (esterno e foro).
- Spessore base regolabile per modello (±0.6 mm rispetto al default STEP, passo 0.2 mm) e spessore testo 0.6 mm.
- Modalita' di rilievo selezionabile per tutti i modelli:
  * "flush" (a filo T-0.6..T, stampata face-down con sottrazione geometrica 2.5D dalla base)
  * "raised" (in rilievo T..T+0.6 sopra la base, stampata rivolta verso l'alto)
- Adattamento automatico della dimensione del testo all'area utile (singola o multi-riga).
- Esportazione in .3mf multi-colore (Bambu Studio / OrcaSlicer) e in 2 file .stl separati.
"""

from __future__ import annotations

import io
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import shapely
import shapely.affinity as sa
import shapely.geometry as sg
import shapely.ops as so
import trimesh
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

TEXT_THICKNESS = 0.6
TEXT_INSERT_DEPTH_MM = 0.2   # inserimento fisso nella base in modalita' in rilievo
MIN_RELIEF_HEIGHT_MM = 0.4
DEFAULT_RELIEF_HEIGHT_MM = 0.6
MAX_RELIEF_HEIGHT_MM = 1.6
RELIEF_STEP_MM = 0.2
CHAMFER_MM = 0.2
BORDER_RAISED_HEIGHT = 0.4  # bordino circolare opzionale in rilievo sopra la base
THICKNESS_STEP_MM = 0.2

# Parametri geometrici estratti dai nuovi modelli STEP in modelli/
PILL_HOLE_RIM_MM = 4.0       # 12.5 - 8.5 (foro Ø 17.0 mm a larghezza 25 mm)
RECT_CORNER_RADIUS_MM = 5.0
RECT_HOLE_RADIUS_MM = 2.5    # Ø 5.0 mm
RECT_HOLE_OFFSET_LEFT_MM = 6.0
RECT_HOLE_OFFSET_TOP_MM = 6.0
ROUND_HOLE_RADIUS_MM = 2.5   # Ø 5.0 mm
ROUND_HOLE_OFFSET_TOP_MM = 5.5  # 17.5 - 12.0
ROUND_BORDER_WIDTH_MM = 1.0
ROUND_BORDER_INSET_MM = CHAMFER_MM + 0.05  # rientro dopo lo smusso 0.2 mm

DEFAULT_BASE_COLOR = "#FDE68A"
DEFAULT_TEXT_COLOR = "#000000"
DEFAULT_MARGIN_MM = 2.5
AUTO_WRAP_MIN_LINE_HEIGHT_MM = 5.2

PREFERRED_FONTS = [
    "Arial Narrow Bold",
    "Bahnschrift",
    "Arial Bold",
    "Segoe UI Bold",
    "Impact",
    "Calibri Bold",
    "Verdana Bold",
    "Tahoma Bold",
]


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    display_name: str
    default_width_mm: float
    min_width_mm: float
    max_width_mm: float
    default_height_mm: float
    min_height_mm: float
    max_height_mm: float
    default_thickness_mm: float
    min_thickness_mm: float
    max_thickness_mm: float
    default_base_color: str
    default_text_color: str
    default_relief_mode: str  # "flush" | "raised"
    text_orientation: str     # "vertical" | "horizontal"
    single_dimension: bool = False
    supports_border: bool = False
    default_include_border: bool = False
    chamfer_mm: float = CHAMFER_MM


MODEL_SPECS: dict[str, ModelSpec] = {
    "pill": ModelSpec(
        model_id="pill",
        display_name="Pillola verticale (75×25 mm)",
        default_width_mm=25.0,
        min_width_mm=20.0,
        max_width_mm=30.0,
        default_height_mm=75.0,
        min_height_mm=65.0,
        max_height_mm=85.0,
        default_thickness_mm=1.8,
        min_thickness_mm=1.2,
        max_thickness_mm=2.4,
        default_base_color=DEFAULT_BASE_COLOR,
        default_text_color=DEFAULT_TEXT_COLOR,
        default_relief_mode="flush",
        text_orientation="vertical",
    ),
    "rectangular": ModelSpec(
        model_id="rectangular",
        display_name="Rettangolare orizzontale (50×80 mm)",
        default_width_mm=80.0,
        min_width_mm=70.0,
        max_width_mm=90.0,
        default_height_mm=50.0,
        min_height_mm=40.0,
        max_height_mm=60.0,
        default_thickness_mm=1.6,
        min_thickness_mm=1.0,
        max_thickness_mm=2.2,
        default_base_color=DEFAULT_BASE_COLOR,
        default_text_color=DEFAULT_TEXT_COLOR,
        default_relief_mode="raised",
        text_orientation="horizontal",
    ),
    "round": ModelSpec(
        model_id="round",
        display_name="Circolare (Ø 35 mm)",
        default_width_mm=35.0,
        min_width_mm=30.0,
        max_width_mm=40.0,
        default_height_mm=35.0,
        min_height_mm=30.0,
        max_height_mm=40.0,
        default_thickness_mm=1.6,
        min_thickness_mm=1.0,
        max_thickness_mm=2.2,
        default_base_color=DEFAULT_BASE_COLOR,
        default_text_color=DEFAULT_TEXT_COLOR,
        default_relief_mode="raised",
        text_orientation="horizontal",
        single_dimension=True,
        supports_border=True,
        default_include_border=False,
    ),
}

DEFAULT_MODEL_ID = "pill"
DEFAULT_WIDTH_MM = MODEL_SPECS[DEFAULT_MODEL_ID].default_width_mm
DEFAULT_HEIGHT_MM = MODEL_SPECS[DEFAULT_MODEL_ID].default_height_mm
DEFAULT_THICKNESS_MM = MODEL_SPECS[DEFAULT_MODEL_ID].default_thickness_mm
MIN_WIDTH_MM = MODEL_SPECS[DEFAULT_MODEL_ID].min_width_mm
MAX_WIDTH_MM = MODEL_SPECS[DEFAULT_MODEL_ID].max_width_mm
MIN_HEIGHT_MM = MODEL_SPECS[DEFAULT_MODEL_ID].min_height_mm
MAX_HEIGHT_MM = MODEL_SPECS[DEFAULT_MODEL_ID].max_height_mm


@dataclass(frozen=True)
class FontInfo:
    display_name: str
    path: str
    font_number: int = 0


@dataclass
class BaseProfile:
    """Profili 2D analitici con corrispondenza 1-a-1 tra sagoma piena e facce smussate."""
    full_polygon: sg.Polygon
    chamfer_polygon: sg.Polygon
    outer_full: np.ndarray
    hole_full: np.ndarray
    outer_chamf: np.ndarray
    hole_chamf: np.ndarray
    chamfer_mm: float = CHAMFER_MM


@dataclass
class TagLayout:
    text: str
    lines: list[str]
    base_polygon: sg.Polygon
    usable_polygon: sg.base.BaseGeometry
    text_polygon: sg.base.BaseGeometry
    font_scale_mm: float
    line_height_mm: float
    width_mm: float = DEFAULT_WIDTH_MM
    height_mm: float = DEFAULT_HEIGHT_MM
    thickness_mm: float = DEFAULT_THICKNESS_MM
    chamfer_mm: float = CHAMFER_MM
    model_id: str = DEFAULT_MODEL_ID
    relief_mode: str = "flush"
    relief_height_mm: float = DEFAULT_RELIEF_HEIGHT_MM
    align: str = "center"
    border_polygon: sg.base.BaseGeometry = field(default_factory=sg.GeometryCollection)
    include_border: bool = False
    base_profile: BaseProfile | None = None


@dataclass
class TagMeshes:
    layout: TagLayout
    base_mesh: trimesh.Trimesh
    text_mesh: trimesh.Trimesh


def get_model_spec(model_id: str) -> ModelSpec:
    if model_id not in MODEL_SPECS:
        raise ValueError(f"Modello sconosciuto: {model_id!r}")
    return MODEL_SPECS[model_id]


def sanitize_filename(text: str) -> str:
    """Converte il testo dell'etichetta in un nome file sicuro."""
    cleaned = text.strip().replace("\r\n", " ").replace("\n", " ")
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned or "etichetta"


def _read_ttf_display_name(tt: TTFont) -> str | None:
    name_table = tt.get("name")
    if not name_table:
        return None
    for platform_id, enc_id, lang_id in [(3, 1, 0x0409), (3, 10, 0x0409), (3, 1, 0x0410), (1, 0, 0)]:
        rec = name_table.getName(4, platform_id, enc_id, lang_id)
        if rec:
            val = rec.toUnicode().strip()
            if val:
                return val
    for rec in name_table.names:
        if rec.nameID == 4:
            try:
                val = rec.toUnicode().strip()
                if val:
                    return val
            except Exception:
                continue
    return None


def discover_system_fonts() -> list[FontInfo]:
    """Scansiona i font TTF/OTF installati su Windows (sistema e utente)."""
    font_dirs = [Path(r"C:\Windows\Fonts")]
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        font_dirs.append(Path(local_app) / "Microsoft" / "Windows" / "Fonts")

    found: dict[str, FontInfo] = {}
    for folder in font_dirs:
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.suffix.lower() not in {".ttf", ".otf"}:
                continue
            try:
                with TTFont(str(entry), lazy=True) as tt:
                    if "glyf" not in tt and "CFF " not in tt and "CFF2" not in tt:
                        continue
                    disp = _read_ttf_display_name(tt) or entry.stem
            except Exception:
                continue
            if disp not in found:
                found[disp] = FontInfo(display_name=disp, path=str(entry), font_number=0)

    return sorted(found.values(), key=lambda f: f.display_name.lower())


def pick_default_font(fonts: list[FontInfo]) -> FontInfo | None:
    by_lower = {f.display_name.lower(): f for f in fonts}
    for pref in PREFERRED_FONTS:
        if pref.lower() in by_lower:
            return by_lower[pref.lower()]
    return fonts[0] if fonts else None


class _ShapelyGlyphPen(BasePen):
    """Converte i contorni vettroriali di un glifo TrueType/OpenType in anelli 2D."""

    def __init__(self, glyph_set, flatness: float):
        super().__init__(glyph_set)
        self.flatness = flatness
        self.contours: list[list[tuple[float, float]]] = []
        self._current: list[tuple[float, float]] = []
        self._last_pt: tuple[float, float] = (0.0, 0.0)

    def _moveTo(self, pt):
        if len(self._current) >= 3:
            self.contours.append(self._current)
        p = (float(pt[0]), float(pt[1]))
        self._current = [p]
        self._last_pt = p

    def _lineTo(self, pt):
        p = (float(pt[0]), float(pt[1]))
        if p != self._last_pt:
            self._current.append(p)
            self._last_pt = p

    def _curveToOne(self, pt1, pt2, pt3):
        p0 = self._last_pt
        p1 = (float(pt1[0]), float(pt1[1]))
        p2 = (float(pt2[0]), float(pt2[1]))
        p3 = (float(pt3[0]), float(pt3[1]))
        self._flatten_cubic(p0, p1, p2, p3, depth=0)
        self._last_pt = p3

    def _flatten_cubic(self, p0, p1, p2, p3, depth: int):
        if depth >= 8:
            self._current.append(p3)
            return
        dx = p3[0] - p0[0]
        dy = p3[1] - p0[1]
        norm2 = dx * dx + dy * dy
        if norm2 < 1e-12:
            d1 = np.hypot(p1[0] - p0[0], p1[1] - p0[1])
            d2 = np.hypot(p2[0] - p0[0], p2[1] - p0[1])
            err = max(d1, d2)
        else:
            inv = 1.0 / np.sqrt(norm2)
            d1 = abs((p1[0] - p0[0]) * dy - (p1[1] - p0[1]) * dx) * inv
            d2 = abs((p2[0] - p0[0]) * dy - (p2[1] - p0[1]) * dx) * inv
            err = max(d1, d2)

        if err <= self.flatness:
            self._current.append(p3)
            return

        p01 = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)
        p12 = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
        p23 = ((p2[0] + p3[0]) * 0.5, (p2[1] + p3[1]) * 0.5)
        p012 = ((p01[0] + p12[0]) * 0.5, (p01[1] + p12[1]) * 0.5)
        p123 = ((p12[0] + p23[0]) * 0.5, (p12[1] + p23[1]) * 0.5)
        p0123 = ((p012[0] + p123[0]) * 0.5, (p012[1] + p123[1]) * 0.5)
        self._flatten_cubic(p0, p01, p012, p0123, depth + 1)
        self._flatten_cubic(p0123, p123, p23, p3, depth + 1)

    def _closePath(self):
        if len(self._current) >= 3:
            self.contours.append(self._current)
        self._current = []

    def _endPath(self):
        self._closePath()

    def to_geometry(self) -> sg.base.BaseGeometry:
        if len(self._current) >= 3:
            self.contours.append(self._current)
            self._current = []

        parsed: list[tuple[float, sg.Polygon]] = []
        for pts in self.contours:
            arr = np.asarray(pts, dtype=np.float64)
            x, y = arr[:, 0], arr[:, 1]
            signed_area = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
            if abs(signed_area) < 1e-6:
                continue
            poly = sg.Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty or poly.area < 1e-6:
                continue
            parsed.append((signed_area, poly))

        if not parsed:
            return sg.GeometryCollection()

        parsed.sort(key=lambda item: abs(item[0]), reverse=True)
        outer_sign = parsed[0][0] > 0

        result: sg.base.BaseGeometry = sg.GeometryCollection()
        for signed_area, poly in parsed:
            is_outer = (signed_area > 0) == outer_sign
            if result.is_empty:
                result = poly
            elif is_outer:
                result = result.union(poly)
            else:
                result = result.difference(poly)

        return result.buffer(0) if not result.is_empty else sg.GeometryCollection()


@lru_cache(maxsize=16)
def _load_font_data(font_path: str, font_number: int = 0):
    tt = TTFont(font_path, fontNumber=font_number)
    upm = float(tt["head"].unitsPerEm)
    cmap = tt.getBestCmap() or {}
    glyph_set = tt.getGlyphSet()
    hmtx = tt["hmtx"]
    kern_pairs: dict[tuple[str, str], float] = {}
    if "kern" in tt:
        for subtable in getattr(tt["kern"], "kernTables", []):
            if getattr(subtable, "format", None) == 0 and hasattr(subtable, "kernTable"):
                for k, v in subtable.kernTable.items():
                    kern_pairs[k] = float(v)
    return tt, upm, cmap, glyph_set, hmtx, kern_pairs


@lru_cache(maxsize=2048)
def _get_unit_glyph(font_path: str, font_number: int, char: str) -> tuple[sg.base.BaseGeometry, str | None, float]:
    _, upm, cmap, glyph_set, hmtx, _ = _load_font_data(font_path, font_number)
    gname = cmap.get(ord(char))
    if gname is None or gname not in glyph_set:
        if ".notdef" in glyph_set:
            gname = ".notdef"
        else:
            return sg.GeometryCollection(), None, 0.5

    advance_units = float(hmtx[gname][0]) / upm
    pen = _ShapelyGlyphPen(glyph_set, flatness=max(upm * 0.0025, 1.0))
    glyph_set[gname].draw(pen)
    geom = pen.to_geometry()
    if not geom.is_empty:
        geom = sa.scale(geom, xfact=1.0 / upm, yfact=1.0 / upm, origin=(0.0, 0.0))
    return geom, gname, advance_units


def _layout_line_horizontal(line: str, font_path: str, font_number: int = 0) -> tuple[sg.base.BaseGeometry, float]:
    """Costruisce la geometria 2D orizzontale di una riga in scala unitaria (1 EM = 1 mm)."""
    _, upm, _, _, _, kern_pairs = _load_font_data(font_path, font_number)
    cursor_x = 0.0
    prev_gname: str | None = None
    polys: list[sg.base.BaseGeometry] = []

    for ch in line:
        geom, gname, adv = _get_unit_glyph(font_path, font_number, ch)
        if prev_gname and gname:
            cursor_x += kern_pairs.get((prev_gname, gname), 0.0) / upm
        if not geom.is_empty:
            polys.append(sa.translate(geom, xoff=cursor_x, yoff=0.0))
        cursor_x += adv
        prev_gname = gname

    if not polys:
        return sg.GeometryCollection(), max(cursor_x, 0.0)
    merged = so.unary_union(polys).buffer(0)
    return merged, cursor_x


def _build_multiline_unit(
    lines: list[str],
    font_path: str,
    font_number: int = 0,
    orientation: str = "vertical",
    align: str = "center",
    line_spacing: float = 1.15,
) -> tuple[sg.base.BaseGeometry, float]:
    """
    Combina piu' righe con allineamento (`center` o `left`) e orientamento (`vertical` -90 deg o `horizontal` 0 deg).
    Restituisce (geometria_centrata_su_orig, altezza_media_riga_in_em).
    """
    rendered_lines: list[sg.base.BaseGeometry] = []
    line_heights: list[float] = []

    for idx, line in enumerate(lines):
        geom, _ = _layout_line_horizontal(line, font_path, font_number)
        if geom.is_empty:
            continue
        min_u, min_v, max_u, max_v = geom.bounds
        line_heights.append(max_v - min_v)
        if align == "left":
            u_shift = -min_u
        else:
            u_shift = -(min_u + max_u) * 0.5
        aligned = sa.translate(geom, xoff=u_shift, yoff=-idx * line_spacing)
        rendered_lines.append(aligned)

    if not rendered_lines:
        return sg.GeometryCollection(), 0.72

    horiz = so.unary_union(rendered_lines).buffer(0)
    geom_out = sa.rotate(horiz, -90.0, origin=(0.0, 0.0)) if orientation == "vertical" else horiz
    minx, miny, maxx, maxy = geom_out.bounds
    geom_out = sa.translate(geom_out, xoff=-(minx + maxx) * 0.5, yoff=-(miny + maxy) * 0.5)
    avg_cap = float(np.mean(line_heights)) if line_heights else 0.72
    return geom_out, avg_cap


def _circle_ring(cx: float, cy: float, radius: float, n_pts: int) -> np.ndarray:
    angles = np.linspace(0.0, 2.0 * np.pi, n_pts, endpoint=False)
    return np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])


def _pill_outer_ring(r_outer: float, cy_cap: float, n_arc: int = 65) -> np.ndarray:
    angles_bot = np.linspace(np.pi, 2.0 * np.pi, n_arc)
    angles_top = np.linspace(0.0, np.pi, n_arc)
    bot = np.column_stack([r_outer * np.cos(angles_bot), -cy_cap + r_outer * np.sin(angles_bot)])
    top = np.column_stack([r_outer * np.cos(angles_top), cy_cap + r_outer * np.sin(angles_top)])
    return np.vstack([bot, top])


def _rounded_rect_outer_ring(w: float, h: float, r_base: float, r_offset: float, n_corner: int = 17) -> np.ndarray:
    """
    Costruisce l'anello esterno CCW di un rettangolo arrotondato con centri degli archi fissi
    a (±(w/2 - r_base), ±(h/2 - r_base)) e raggio `r_offset` (= r_base oppure r_base - chamfer).
    """
    hx = w * 0.5 - r_base
    hy = h * 0.5 - r_base
    corners = [
        (hx, -hy, -0.5 * np.pi, 0.0),
        (hx, hy, 0.0, 0.5 * np.pi),
        (-hx, hy, 0.5 * np.pi, np.pi),
        (-hx, -hy, np.pi, 1.5 * np.pi),
    ]
    segs = []
    for cx, cy, a0, a1 in corners:
        ang = np.linspace(a0, a1, n_corner)
        segs.append(np.column_stack([cx + r_offset * np.cos(ang), cy + r_offset * np.sin(ang)]))
    return np.vstack(segs)


def build_base_profile(
    width_mm: float = DEFAULT_WIDTH_MM,
    height_mm: float = DEFAULT_HEIGHT_MM,
    model_id: str = DEFAULT_MODEL_ID,
    include_border: bool = False,
) -> tuple[BaseProfile, sg.base.BaseGeometry, sg.base.BaseGeometry, float, float]:
    """
    Costruisce il profilo 2D analitico del modello scelto (`pill`, `rectangular` o `round`),
    includendo sia la sagoma piena che la faccia piana smussata a 45° con corrispondenza 1-a-1.
    Restituisce (BaseProfile, clip_area_utile, poligono_bordino, width_clamped, height_clamped).
    """
    spec = get_model_spec(model_id)
    w = float(np.clip(width_mm, spec.min_width_mm, spec.max_width_mm))
    h = float(np.clip(height_mm, spec.min_height_mm, spec.max_height_mm))
    c = spec.chamfer_mm
    empty_border = sg.GeometryCollection()

    if model_id == "pill":
        r_outer = w * 0.5
        cy_cap = h * 0.5 - r_outer
        r_hole = max(1.0, r_outer - PILL_HOLE_RIM_MM)

        outer_full = _pill_outer_ring(r_outer, cy_cap, n_arc=65)
        outer_chamf = _pill_outer_ring(r_outer - c, cy_cap, n_arc=65)
        hole_full = _circle_ring(0.0, cy_cap, r_hole, 64)
        hole_chamf = _circle_ring(0.0, cy_cap, r_hole + c, 64)

        full_poly = sg.Polygon(outer_full, [hole_full])
        chamf_poly = sg.Polygon(outer_chamf, [hole_chamf])
        profile = BaseProfile(full_poly, chamf_poly, outer_full, hole_full, outer_chamf, hole_chamf, c)

        hole_bottom_y = cy_cap - (r_hole + c)
        clip_box = sg.box(-w, -h, w, hole_bottom_y)
        return profile, clip_box, empty_border, w, h

    if model_id == "round":
        d = w
        h = d
        r_outer = d * 0.5
        hole_cy = r_outer - ROUND_HOLE_OFFSET_TOP_MM

        outer_full = _circle_ring(0.0, 0.0, r_outer, 128)
        outer_chamf = _circle_ring(0.0, 0.0, r_outer - c, 128)
        hole_full = _circle_ring(0.0, hole_cy, ROUND_HOLE_RADIUS_MM, 64)
        hole_chamf = _circle_ring(0.0, hole_cy, ROUND_HOLE_RADIUS_MM + c, 64)

        full_poly = sg.Polygon(outer_full, [hole_full])
        chamf_poly = sg.Polygon(outer_chamf, [hole_chamf])
        profile = BaseProfile(full_poly, chamf_poly, outer_full, hole_full, outer_chamf, hole_chamf, c)

        hole_bottom_y = hole_cy - (ROUND_HOLE_RADIUS_MM + c)
        if include_border:
            r_b_out = r_outer - ROUND_BORDER_INSET_MM
            r_b_in = r_b_out - ROUND_BORDER_WIDTH_MM
            b_outer_circle = sg.Point(0.0, 0.0).buffer(r_b_out, quad_segs=32)
            b_inner_circle = sg.Point(0.0, 0.0).buffer(r_b_in, quad_segs=32)
            border_poly = b_outer_circle.difference(b_inner_circle).buffer(0)
            clip_region = b_inner_circle.intersection(sg.box(-d, -d, d, hole_bottom_y)).buffer(0)
        else:
            border_poly = empty_border
            clip_region = sg.box(-d, -d, d, hole_bottom_y)
        return profile, clip_region, border_poly, d, d

    # rectangular: rettangolo arrotondato (r=5 mm) e foro Ø 5 mm in alto a sinistra a 6x6 mm
    r_corner = RECT_CORNER_RADIUS_MM
    hole_cx = -w * 0.5 + RECT_HOLE_OFFSET_LEFT_MM
    hole_cy = h * 0.5 - RECT_HOLE_OFFSET_TOP_MM

    outer_full = _rounded_rect_outer_ring(w, h, r_corner, r_corner, n_corner=17)
    outer_chamf = _rounded_rect_outer_ring(w, h, r_corner, r_corner - c, n_corner=17)
    hole_full = _circle_ring(hole_cx, hole_cy, RECT_HOLE_RADIUS_MM, 64)
    hole_chamf = _circle_ring(hole_cx, hole_cy, RECT_HOLE_RADIUS_MM + c, 64)

    full_poly = sg.Polygon(outer_full, [hole_full])
    chamf_poly = sg.Polygon(outer_chamf, [hole_chamf])
    profile = BaseProfile(full_poly, chamf_poly, outer_full, hole_full, outer_chamf, hole_chamf, c)

    hole_right_x = hole_cx + (RECT_HOLE_RADIUS_MM + c)
    clip_box = sg.box(hole_right_x, -h, w, h)
    return profile, clip_box, empty_border, w, h


def build_base_polygon(
    width_mm: float = DEFAULT_WIDTH_MM,
    height_mm: float = DEFAULT_HEIGHT_MM,
    model_id: str = DEFAULT_MODEL_ID,
    include_border: bool = False,
) -> tuple[sg.Polygon, sg.base.BaseGeometry, sg.base.BaseGeometry, float, float]:
    """Wrapper di compatibilita' che restituisce il solo poligono pieno."""
    profile, clip_region, border_poly, w, h = build_base_profile(
        width_mm=width_mm,
        height_mm=height_mm,
        model_id=model_id,
        include_border=include_border,
    )
    return profile.full_polygon, clip_region, border_poly, w, h


def compute_usable_polygon(
    base_polygon: sg.Polygon,
    clip_region: sg.base.BaseGeometry,
    margin_mm: float = DEFAULT_MARGIN_MM,
    chamfer_polygon: sg.Polygon | None = None,
) -> sg.base.BaseGeometry:
    """Calcola l'area utile rispettando il margine da bordo esterno, smusso, foro e zona sicura."""
    margin_mm = max(0.5, min(margin_mm, 8.0))
    shrunk_base = base_polygon.buffer(-margin_mm)
    shrunk_clip = clip_region.buffer(-margin_mm)
    usable = shrunk_base.intersection(shrunk_clip)
    if chamfer_polygon is not None:
        usable = usable.intersection(chamfer_polygon.buffer(-0.2))
    return usable.buffer(0)


def _wrap_words_into_k_lines(words: list[str], k: int) -> list[str]:
    if k <= 1 or len(words) <= 1:
        return [" ".join(words)]
    k = min(k, len(words))
    total_chars = sum(len(w) for w in words) + (len(words) - 1)
    target = total_chars / k
    lines: list[str] = []
    cur: list[str] = []
    cur_len = 0

    for i, w in enumerate(words):
        remaining_words = len(words) - i
        remaining_lines = k - len(lines)
        if cur and (cur_len + 1 + len(w) > target * 1.12 or remaining_words == remaining_lines):
            if remaining_words >= remaining_lines:
                lines.append(" ".join(cur))
                cur = [w]
                cur_len = len(w)
                continue
        cur.append(w)
        cur_len += (1 if len(cur) > 1 else 0) + len(w)

    if cur:
        lines.append(" ".join(cur))
    return lines


def _place_scaled_text(
    unit_geom: sg.base.BaseGeometry,
    scale: float,
    usable_bounds: tuple[float, float, float, float],
    orientation: str,
    align: str,
    model_id: str = DEFAULT_MODEL_ID,
) -> sg.base.BaseGeometry:
    uminx, uminy, umaxx, umaxy = usable_bounds
    target_cx = (uminx + umaxx) * 0.5
    target_cy = (uminy + umaxy) * 0.5

    scaled = sa.scale(unit_geom, xfact=scale, yfact=scale, origin=(0.0, 0.0))
    sminx, sminy, smaxx, smaxy = scaled.bounds

    if model_id == "round" and orientation == "horizontal":
        # Sul disco circolare centra a Y=0 finche' non tocca il margine del foro, poi scende quanto basta
        half_h = (smaxy - sminy) * 0.5
        mid_y = (sminy + smaxy) * 0.5
        desired_cy = min(0.0, umaxy - half_h)
        desired_cy = max(target_cy, desired_cy)
        xoff = uminx - sminx if align == "left" else target_cx
        yoff = desired_cy - mid_y
        return sa.translate(scaled, xoff=xoff, yoff=yoff)

    if align == "left" and orientation == "horizontal":
        xoff = uminx - sminx
        yoff = target_cy
    elif align == "left" and orientation == "vertical":
        xoff = target_cx
        yoff = umaxy - smaxy
    else:
        xoff = target_cx
        yoff = target_cy

    return sa.translate(scaled, xoff=xoff, yoff=yoff)


def _fit_unit_geometry(
    unit_geom: sg.base.BaseGeometry,
    usable: sg.base.BaseGeometry,
    orientation: str = "vertical",
    align: str = "center",
    model_id: str = DEFAULT_MODEL_ID,
) -> tuple[sg.base.BaseGeometry, float]:
    """Trova per bisezione la scala massima (mm per 1 EM) che sta interamente in `usable`."""
    if unit_geom.is_empty or usable.is_empty:
        return sg.GeometryCollection(), 0.0

    ubounds = usable.bounds
    lo, hi = 0.2, 60.0
    best_scale = lo
    best_geom = _place_scaled_text(unit_geom, lo, ubounds, orientation, align, model_id)

    for _ in range(26):
        mid = (lo + hi) * 0.5
        cand = _place_scaled_text(unit_geom, mid, ubounds, orientation, align, model_id)
        if usable.covers(cand):
            best_scale = mid
            best_geom = cand
            lo = mid
        else:
            hi = mid

    return best_geom.buffer(0), best_scale


def compute_tag_layout(
    text: str,
    font_path: str,
    font_number: int = 0,
    margin_mm: float = DEFAULT_MARGIN_MM,
    wrap_mode: str = "auto",
    line_spacing: float = 1.15,
    width_mm: float | None = None,
    height_mm: float | None = None,
    thickness_mm: float | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    relief_mode: str | None = None,
    relief_height_mm: float = DEFAULT_RELIEF_HEIGHT_MM,
    align: str = "center",
    include_border: bool = False,
) -> TagLayout:
    """Calcola layout, eventuale a capo automatico e dimensione ottimale del testo."""
    spec = get_model_spec(model_id)
    w_req = spec.default_width_mm if width_mm is None else width_mm
    h_req = spec.default_height_mm if height_mm is None else height_mm
    t_req = spec.default_thickness_mm if thickness_mm is None else thickness_mm
    t_clamped = round(float(np.clip(t_req, spec.min_thickness_mm, spec.max_thickness_mm)), 2)
    relief = relief_mode if relief_mode in ("flush", "raised") else spec.default_relief_mode
    relief_h = round(float(np.clip(relief_height_mm, MIN_RELIEF_HEIGHT_MM, MAX_RELIEF_HEIGHT_MM)), 2)
    align_norm = align if align in ("center", "left") else "center"
    use_border = bool(include_border and spec.supports_border)

    profile, clip_region, border_poly, w_clamped, h_clamped = build_base_profile(
        w_req, h_req, model_id=model_id, include_border=use_border
    )
    base_poly = profile.full_polygon
    usable = compute_usable_polygon(
        base_poly,
        clip_region,
        margin_mm,
        chamfer_polygon=profile.chamfer_polygon,
    )
    raw = text.replace("\r\n", "\n").strip("\n")

    def _make_layout(
        lines: list[str],
        text_poly: sg.base.BaseGeometry,
        font_scale: float,
        line_h: float,
    ) -> TagLayout:
        return TagLayout(
            text=text,
            lines=lines,
            base_polygon=base_poly,
            usable_polygon=usable,
            text_polygon=text_poly,
            font_scale_mm=font_scale,
            line_height_mm=line_h,
            width_mm=w_clamped,
            height_mm=h_clamped,
            thickness_mm=t_clamped,
            chamfer_mm=profile.chamfer_mm,
            model_id=model_id,
            relief_mode=relief,
            relief_height_mm=relief_h,
            align=align_norm,
            border_polygon=border_poly,
            include_border=use_border,
            base_profile=profile,
        )

    if not raw.strip():
        return _make_layout([], sg.GeometryCollection(), 0.0, 0.0)

    manual_lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]

    if len(manual_lines) > 1 or wrap_mode == "single":
        lines = manual_lines
        unit_geom, avg_cap = _build_multiline_unit(
            lines, font_path, font_number, spec.text_orientation, align_norm, line_spacing
        )
        fitted, scale = _fit_unit_geometry(unit_geom, usable, spec.text_orientation, align_norm, model_id)
        return _make_layout(lines, fitted, scale, scale * avg_cap)

    single_line = manual_lines[0]
    unit1, cap1 = _build_multiline_unit(
        [single_line], font_path, font_number, spec.text_orientation, align_norm, line_spacing
    )
    fit1, scale1 = _fit_unit_geometry(unit1, usable, spec.text_orientation, align_norm, model_id)
    height1 = scale1 * cap1

    words = single_line.split()
    if height1 >= AUTO_WRAP_MIN_LINE_HEIGHT_MM or len(words) <= 1:
        return _make_layout([single_line], fit1, scale1, height1)

    best_lines = [single_line]
    best_fit = fit1
    best_scale = scale1
    best_height = height1

    max_k = min(4, len(words))
    for k in range(2, max_k + 1):
        cand_lines = _wrap_words_into_k_lines(words, k)
        if len(cand_lines) <= 1:
            continue
        unit_k, cap_k = _build_multiline_unit(
            cand_lines, font_path, font_number, spec.text_orientation, align_norm, line_spacing
        )
        fit_k, scale_k = _fit_unit_geometry(unit_k, usable, spec.text_orientation, align_norm, model_id)
        height_k = scale_k * cap_k
        if height_k > best_height * 1.03:
            best_lines = cand_lines
            best_fit = fit_k
            best_scale = scale_k
            best_height = height_k

    return _make_layout(best_lines, best_fit, best_scale, best_height)


def _geom_to_polys(geom: sg.base.BaseGeometry) -> list[sg.Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, sg.Polygon):
        return [geom] if geom.area > 1e-8 else []
    if isinstance(geom, (sg.MultiPolygon, sg.GeometryCollection)):
        out: list[sg.Polygon] = []
        for g in geom.geoms:
            out.extend(_geom_to_polys(g))
        return out
    return []


def _build_cap(geom: sg.base.BaseGeometry, z: float, flip_normal: bool) -> tuple[np.ndarray, np.ndarray]:
    """Triangola in 2D con Constrained Delaunay Triangulation (senza triangoli degeneri su linee collineari)."""
    polys = _geom_to_polys(geom)
    if not polys:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)

    tri_chunks: list[np.ndarray] = []
    for poly in polys:
        cdt = shapely.constrained_delaunay_triangles(poly)
        if cdt.is_empty:
            continue
        coords = shapely.get_coordinates(cdt)
        if len(coords) < 4:
            continue
        tri_chunks.append(coords.reshape(-1, 4, 2)[:, :3, :])

    if not tri_chunks:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)

    tris_2d = np.vstack(tri_chunks)  # (N, 3, 2)
    a, b, c = tris_2d[:, 0], tris_2d[:, 1], tris_2d[:, 2]
    cross = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    # Garantisce normale verso +Z prima dell'eventuale flip
    swap = cross < 0
    if np.any(swap):
        tris_2d[swap] = tris_2d[swap][:, [0, 2, 1]]
    if flip_normal:
        tris_2d = tris_2d[:, [0, 2, 1]]

    n_tris = len(tris_2d)
    flat_xy = tris_2d.reshape(-1, 2)
    verts_3d = np.column_stack([flat_xy, np.full(len(flat_xy), z)])
    faces = np.arange(len(flat_xy), dtype=np.int64).reshape(n_tris, 3)
    return verts_3d, faces


def _build_loft_band(
    ring0,
    z0: float,
    ring1,
    z1: float,
    outward_ccw: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Collega due anelli chiusi 2D con corrispondenza 1-a-1 tra quota `z0` e `z1` (parete o smusso)."""
    pts0 = np.asarray(ring0, dtype=np.float64)[:, :2]
    pts1 = np.asarray(ring1, dtype=np.float64)[:, :2]
    if len(pts0) > 1 and np.allclose(pts0[0], pts0[-1]):
        pts0 = pts0[:-1]
    if len(pts1) > 1 and np.allclose(pts1[0], pts1[-1]):
        pts1 = pts1[:-1]
    n = len(pts0)
    if n < 3 or len(pts1) != n:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    x, y = pts0[:, 0], pts0[:, 1]
    area2 = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    is_ccw = area2 > 0
    if is_ccw != outward_ccw:
        pts0 = pts0[::-1]
        pts1 = pts1[::-1]
    v_bot = np.column_stack([pts0, np.full(n, z0)])
    v_top = np.column_stack([pts1, np.full(n, z1)])
    verts = np.vstack([v_bot, v_top])
    idx = np.arange(n, dtype=np.int64)
    nxt = (idx + 1) % n
    f1 = np.column_stack([idx, nxt, n + nxt])
    f2 = np.column_stack([idx, n + nxt, n + idx])
    return verts, np.vstack([f1, f2])


def _build_walls(ring_coords, z0: float, z1: float, outward_ccw: bool) -> tuple[np.ndarray, np.ndarray]:
    return _build_loft_band(ring_coords, z0, ring_coords, z1, outward_ccw)


def _combine_mesh_parts(parts: Iterable[tuple[np.ndarray, np.ndarray]]) -> trimesh.Trimesh:
    vs: list[np.ndarray] = []
    fs: list[np.ndarray] = []
    offset = 0
    for v, f in parts:
        if len(f) == 0:
            continue
        vs.append(v)
        fs.append(f + offset)
        offset += len(v)
    if not vs:
        return trimesh.Trimesh()
    return trimesh.Trimesh(vertices=np.vstack(vs), faces=np.vstack(fs), process=True)


def _extrude_geom_range(geom: sg.base.BaseGeometry, z0: float, z1: float) -> trimesh.Trimesh:
    """Estrude una geometria 2D (Polygon o MultiPolygon con fori) tra `z0` e `z1`."""
    parts = [
        _build_cap(geom, z0, flip_normal=True),
        _build_cap(geom, z1, flip_normal=False),
    ]
    parts.extend(_build_geom_walls(geom, z0, z1))
    return _combine_mesh_parts(parts)


def _build_geom_walls(
    geom: sg.base.BaseGeometry,
    z0: float,
    z1: float,
    invert: bool = False,
) -> list[tuple[np.ndarray, np.ndarray]]:
    parts: list[tuple[np.ndarray, np.ndarray]] = []
    for p in _geom_to_polys(geom):
        parts.append(_build_walls(p.exterior.coords, z0, z1, outward_ccw=not invert))
        for h in p.interiors:
            parts.append(_build_walls(h.coords, z0, z1, outward_ccw=invert))
    return parts


def _build_chamfered_base_parts(
    profile: BaseProfile,
    thickness_mm: float,
    top_cap_geom: sg.base.BaseGeometry | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Costruisce la base con smussi 45° sopra e sotto (esterno + foro) garantendo chiusura watertight."""
    c = min(profile.chamfer_mm, thickness_mm * 0.4)
    top_geom = profile.chamfer_polygon if top_cap_geom is None else top_cap_geom
    parts: list[tuple[np.ndarray, np.ndarray]] = [
        _build_cap(profile.chamfer_polygon, 0.0, flip_normal=True),
    ]
    if c > 1e-6:
        parts.append(_build_loft_band(profile.outer_chamf, 0.0, profile.outer_full, c, outward_ccw=True))
        parts.append(_build_loft_band(profile.hole_chamf, 0.0, profile.hole_full, c, outward_ccw=False))
        parts.append(_build_loft_band(profile.outer_full, c, profile.outer_full, thickness_mm - c, outward_ccw=True))
        parts.append(_build_loft_band(profile.hole_full, c, profile.hole_full, thickness_mm - c, outward_ccw=False))
        parts.append(_build_loft_band(profile.outer_full, thickness_mm - c, profile.outer_chamf, thickness_mm, outward_ccw=True))
        parts.append(_build_loft_band(profile.hole_full, thickness_mm - c, profile.hole_chamf, thickness_mm, outward_ccw=False))
    else:
        parts.append(_build_loft_band(profile.outer_full, 0.0, profile.outer_full, thickness_mm, outward_ccw=True))
        parts.append(_build_loft_band(profile.hole_full, 0.0, profile.hole_full, thickness_mm, outward_ccw=False))
    parts.append(_build_cap(top_geom, thickness_mm, flip_normal=False))
    return parts


def _clean_geom(geom: sg.base.BaseGeometry) -> sg.base.BaseGeometry:
    if geom.is_empty:
        return sg.GeometryCollection()
    polys = _geom_to_polys(geom)
    if not polys:
        return sg.GeometryCollection()
    return so.unary_union(polys).simplify(1e-6, preserve_topology=True).buffer(0)


def _build_pocketed_base(
    profile: BaseProfile,
    thickness: float,
    pocket_cut_geom: sg.base.BaseGeometry,
    pocket_z_min: float,
) -> trimesh.Trimesh:
    """Costruisce la base smussata con sede incassata tra `pocket_z_min` e `thickness`."""
    B_top = profile.chamfer_polygon
    R = B_top.difference(pocket_cut_geom).buffer(0)
    pocket_geom = B_top.difference(R).buffer(0)
    b_parts = _build_chamfered_base_parts(profile, thickness, top_cap_geom=R)
    b_parts.extend(_build_geom_walls(pocket_geom, pocket_z_min, thickness, invert=True))
    b_parts.append(_build_cap(pocket_geom, pocket_z_min, flip_normal=False))
    return _combine_mesh_parts(b_parts)


def build_tag_meshes(layout: TagLayout) -> TagMeshes:
    """
    Genera le 2 mesh 3D non sovrapposte e chiuse (watertight) con smussi 0.2 mm x 45°:
    - Modalita' "flush": base Z in [0.0, T] con sede incassata Z in [T-0.6, T]; testo/bordo Z in [T-0.6, T].
    - Modalita' "raised": inserimento fisso -0.2 mm nella base e sporgenza R (0.4..1.6 mm) sopra T:
      testo Z in [T-0.2, T+R] (+ bordino Z in [T-0.2, T+0.4]), sottratti dalla base in [T-0.2, T].
    """
    thickness = float(layout.thickness_mm)
    profile = layout.base_profile
    if profile is None:
        profile, _, _, _, _ = build_base_profile(
            width_mm=layout.width_mm,
            height_mm=layout.height_mm,
            model_id=layout.model_id,
            include_border=layout.include_border,
        )

    T = _clean_geom(layout.text_polygon)
    B_rim = _clean_geom(layout.border_polygon)
    B_top = profile.chamfer_polygon
    safe_top = B_top.buffer(-1e-3)

    if layout.relief_mode == "raised":
        relief_h = float(np.clip(layout.relief_height_mm, MIN_RELIEF_HEIGHT_MM, MAX_RELIEF_HEIGHT_MM))
        insert_z_min = max(profile.chamfer_mm + 0.05, thickness - TEXT_INSERT_DEPTH_MM)
        T_safe = _clean_geom(T.intersection(safe_top)) if not T.is_empty else sg.GeometryCollection()
        B_safe = _clean_geom(B_rim.intersection(safe_top)) if not B_rim.is_empty else sg.GeometryCollection()

        cut_parts = [g for g in (T_safe, B_safe) if not g.is_empty]
        if not cut_parts:
            base_mesh = _combine_mesh_parts(_build_chamfered_base_parts(profile, thickness))
            return TagMeshes(layout=layout, base_mesh=base_mesh, text_mesh=trimesh.Trimesh())

        pocket_cut = _clean_geom(so.unary_union(cut_parts))
        base_mesh = _build_pocketed_base(profile, thickness, pocket_cut, insert_z_min)

        ext2_meshes: list[trimesh.Trimesh] = []
        if not T_safe.is_empty:
            ext2_meshes.append(_extrude_geom_range(T_safe, insert_z_min, thickness + relief_h))
        if not B_safe.is_empty:
            ext2_meshes.append(_extrude_geom_range(B_safe, insert_z_min, thickness + BORDER_RAISED_HEIGHT))
        text_mesh = trimesh.util.concatenate(ext2_meshes) if ext2_meshes else trimesh.Trimesh()
        return TagMeshes(layout=layout, base_mesh=base_mesh, text_mesh=text_mesh)

    # Modalita' "flush": testo e eventuale bordino incassati a filo in [T - 0.6, T]
    cut_parts = [g for g in (T, B_rim) if not g.is_empty]
    if not cut_parts:
        base_mesh = _combine_mesh_parts(_build_chamfered_base_parts(profile, thickness))
        return TagMeshes(layout=layout, base_mesh=base_mesh, text_mesh=trimesh.Trimesh())

    T_cut = _clean_geom(so.unary_union(cut_parts).intersection(safe_top))
    if T_cut.is_empty:
        base_mesh = _combine_mesh_parts(_build_chamfered_base_parts(profile, thickness))
        return TagMeshes(layout=layout, base_mesh=base_mesh, text_mesh=trimesh.Trimesh())

    text_z_min = max(profile.chamfer_mm + 0.1, thickness - TEXT_THICKNESS)
    text_mesh = _extrude_geom_range(T_cut, text_z_min, thickness)
    base_mesh = _build_pocketed_base(profile, thickness, T_cut, text_z_min)

    return TagMeshes(layout=layout, base_mesh=base_mesh, text_mesh=text_mesh)


def _to_plate_orientation(mesh: trimesh.Trimesh, relief_mode: str, thickness_mm: float) -> trimesh.Trimesh:
    """
    Prepara la mesh per il piatto di stampa:
    - "flush": ruota 180° attorno a Y (-x, y, T - z) cosi' il testo a filo poggia sul piatto a Z=0.
    - "raised": mantiene l'orientamento dritto verso l'alto (base a Z=0, rilievo a Z=T..T+0.6).
    """
    if len(mesh.vertices) == 0:
        return mesh
    m = mesh.copy()
    if relief_mode == "flush":
        v = m.vertices.copy()
        v[:, 0] = -v[:, 0]
        v[:, 2] = thickness_mm - v[:, 2]
        m.vertices = v
    return m


def export_stls(meshes: TagMeshes, out_dir: Path, base_stem: str) -> tuple[Path, Path | None]:
    """Esporta 2 file STL separati (base e testo) gia' orientati per il piatto di stampa."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base_path = out_dir / f"{base_stem}_base.stl"
    text_path = out_dir / f"{base_stem}_testo.stl"

    relief = meshes.layout.relief_mode
    thickness = meshes.layout.thickness_mm
    base_plate = _to_plate_orientation(meshes.base_mesh, relief, thickness)
    base_plate.export(str(base_path))

    if len(meshes.text_mesh.vertices) > 0:
        text_plate = _to_plate_orientation(meshes.text_mesh, relief, thickness)
        text_plate.export(str(text_path))
        return base_path, text_path
    return base_path, None


def render_thumbnail_png(
    layout: TagLayout,
    base_color: str = DEFAULT_BASE_COLOR,
    text_color: str = DEFAULT_TEXT_COLOR,
    size: tuple[int, int] = (480, 480),
    fill_ratio: float = 0.68,
) -> bytes:
    """Renderizza un'anteprima PNG ad alta qualità (usata sia per la miniatura 3MF che per i pulsanti)."""
    w, h = size
    scale = 4
    W, H = w * scale, h * scale
    img = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    mm_scale = min((W * fill_ratio) / max(layout.width_mm, 1.0), (H * fill_ratio) / max(layout.height_mm, 1.0))
    cx, cy = W * 0.5, H * 0.5

    def to_px(coords):
        return [(cx + x * mm_scale, cy - y * mm_scale) for x, y in coords]

    def draw_geom(geom: sg.base.BaseGeometry, fill_color: str, hole_color: tuple[int, int, int, int]):
        for poly in _geom_to_polys(geom):
            draw.polygon(to_px(poly.exterior.coords), fill=fill_color)
            for hole in poly.interiors:
                draw.polygon(to_px(hole.coords), fill=hole_color)

    draw_geom(layout.base_polygon, base_color, (255, 255, 255, 0))
    if not layout.border_polygon.is_empty:
        draw_geom(layout.border_polygon, text_color, base_color)
        for poly in _geom_to_polys(layout.base_polygon):
            for hole in poly.interiors:
                draw.polygon(to_px(hole.coords), fill=(255, 255, 255, 0))
    if not layout.text_polygon.is_empty:
        draw_geom(layout.text_polygon, text_color, base_color)

    img = img.resize((w, h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mesh_to_3mf_object_xml(obj_id: int, mesh: trimesh.Trimesh) -> str:
    verts = mesh.vertices
    faces = mesh.faces
    v_lines = [
        f'          <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>'
        for x, y, z in verts
    ]
    t_lines = [
        f'          <triangle v1="{a}" v2="{b}" v3="{c}"/>'
        for a, b, c in faces
    ]
    return (
        f'    <object id="{obj_id}" type="model">\n'
        f'      <mesh>\n'
        f'        <vertices>\n'
        + "\n".join(v_lines)
        + "\n        </vertices>\n"
        f'        <triangles>\n'
        + "\n".join(t_lines)
        + "\n        </triangles>\n"
        f'      </mesh>\n'
        f'    </object>'
    )


def export_3mf(
    meshes: TagMeshes,
    out_path: Path,
    base_color: str = DEFAULT_BASE_COLOR,
    text_color: str = DEFAULT_TEXT_COLOR,
    title: str | None = None,
) -> Path:
    """Esporta un file .3mf multi-colore compatibile con Bambu Studio e OrcaSlicer."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    title_str = title or sanitize_filename(meshes.layout.text)
    has_text = len(meshes.text_mesh.vertices) > 0
    relief = meshes.layout.relief_mode
    thickness = meshes.layout.thickness_mm
    build_transform = (
        f"-1 0 0 0 1 0 0 0 -1 90 70 {thickness:.6g}"
        if relief == "flush"
        else "1 0 0 0 1 0 0 0 1 90 70 0"
    )

    u_obj = str(uuid.uuid4())
    u_build = str(uuid.uuid4())
    u_item = str(uuid.uuid4())

    components_xml = ['        <component p:path="/3D/Objects/object-29.model" objectid="31"/>']
    objects_xml = [_mesh_to_3mf_object_xml(31, meshes.base_mesh)]
    parts_cfg = [
        '    <part id="31" subtype="normal_part">\n'
        '      <metadata key="name" value="Etichetta"/>\n'
        '      <metadata key="extruder" value="1"/>\n'
        '      <mesh_stat edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
        '    </part>'
    ]

    if has_text:
        components_xml.append('        <component p:path="/3D/Objects/object-29.model" objectid="32"/>')
        objects_xml.append(_mesh_to_3mf_object_xml(32, meshes.text_mesh))
        parts_cfg.append(
            '    <part id="32" subtype="normal_part">\n'
            '      <metadata key="name" value="Testo"/>\n'
            '      <metadata key="extruder" value="2"/>\n'
            '      <mesh_stat edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
            '    </part>'
        )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />\n'
        '  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml" />\n'
        '  <Default Extension="png" ContentType="image/png" />\n'
        '  <Default Extension="gcode" ContentType="text/x.gcode"/>\n'
        '</Types>\n'
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rel-1" Target="/3D/3dmodel.model" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '  <Relationship Target="/Auxiliaries/.thumbnails/thumbnail_3mf.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>\n'
        '</Relationships>\n'
    )

    model_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Target="/3D/Objects/object-29.model" Id="rel-29" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '</Relationships>\n'
    )

    root_model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
        'requiredextensions="p">\n'
        '  <metadata name="Application">BambuStudio-01.07.04.52</metadata>\n'
        f'  <metadata name="Title">{_xml_escape(title_str)}</metadata>\n'
        '  <resources>\n'
        f'    <object id="29" p:uuid="{u_obj}" type="model">\n'
        '      <components>\n'
        + "\n".join(components_xml)
        + '\n      </components>\n'
        '    </object>\n'
        '  </resources>\n'
        f'  <build p:uuid="{u_build}">\n'
        f'    <item objectid="29" p:uuid="{u_item}" transform="{build_transform}" printable="1"/>\n'
        '  </build>\n'
        '</model>\n'
    )

    object_model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'requiredextensions="p">\n'
        '  <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        '  <resources>\n'
        + "\n".join(objects_xml)
        + '\n  </resources>\n'
        '</model>\n'
    )

    model_settings = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<config>\n'
        '  <object id="29">\n'
        f'    <metadata key="name" value="{_xml_escape(title_str)}.3mf"/>\n'
        '    <metadata key="extruder" value="1"/>\n'
        '    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>\n'
        + "\n".join(parts_cfg)
        + '\n  </object>\n'
        '  <plate>\n'
        '    <metadata key="plater_id" value="1"/>\n'
        '    <model_instance>\n'
        '      <metadata key="object_id" value="29"/>\n'
        '      <metadata key="instance_id" value="0"/>\n'
        '    </model_instance>\n'
        '  </plate>\n'
        '  <assemble>\n'
        '    <assemble_item object_id="29" instance_id="0" offset="0 0 0"/>\n'
        '  </assemble>\n'
        '</config>\n'
    )

    project_settings = json.dumps({
        "printable_area": ["0x0", "180x0", "180x180", "0x180"],
        "printable_height": "180",
        "bed_exclude_area": [],
        "ironing_type": "top",
        "print_settings_id": "0.20mm Standard @BBL A1M",
        "printer_settings_id": "Bambu Lab A1 mini 0.4 nozzle",
        "different_settings_to_system": ["ironing_type;wall_generator", "", "", ""],
        "wall_generator": "arachne",
        "curr_bed_type": "Textured PEI Plate",
        "filament_colour": [base_color.upper(), text_color.upper()],
        "filament_settings_id": ["Bambu PLA Basic @BBL A1M", "Bambu PLA Basic @BBL A1M"],
        "filament_diameter": ["1.75", "1.75"],
        "filament_is_support": ["0", "0"],
        "printer_model": "Bambu Lab A1 mini",
        "printer_variant": "0.4",
        "nozzle_diameter": ["0.4"],
        "layer_height": "0.2",
        "wall_loops": "2",
        "sparse_infill_density": "15%",
    }, separators=(",", ":"))

    thumb_bytes = render_thumbnail_png(meshes.layout, base_color=base_color, text_color=text_color)

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("3D/_rels/3dmodel.model.rels", model_rels)
        zf.writestr("3D/3dmodel.model", root_model)
        zf.writestr("3D/Objects/object-29.model", object_model)
        zf.writestr("Metadata/model_settings.config", model_settings)
        zf.writestr("Metadata/project_settings.config", project_settings)
        zf.writestr("Metadata/plate_1.png", thumb_bytes)
        zf.writestr("Auxiliaries/.thumbnails/thumbnail_3mf.png", thumb_bytes)

    return out_path


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
