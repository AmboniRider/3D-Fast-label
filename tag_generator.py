"""
Generatore 3D per etichette/targhette multi-colore basato sul modello MakerLab NamePlate V1.1.

Caratteristiche principali:
- Geometria esatta della targhetta (24.0424 x 70.7422 mm, spessore 1.0 mm, foro superiore).
- Testo verticale incassato a filo sulla faccia frontale (Z = 0.4 .. 1.0 mm, spessore 0.6 mm).
- Adattamento automatico della dimensione del testo all'area utile (singola o multi-riga).
- Sottrazione geometrica 2.5D pulita: nessuna sovrapposizione tra mesh base e mesh testo.
- Esportazione in .3mf multi-colore (struttura Bambu Studio / OrcaSlicer) e in 2 file .stl separati.
"""

from __future__ import annotations

import io
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import mapbox_earcut
import numpy as np
import shapely.affinity as sa
import shapely.geometry as sg
import shapely.ops as so
import trimesh
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

# Dimensioni esatte (mm) estratte dal modello di riferimento San_P_0.3mf
BASE_OUTER_COORDS = [
    (-1.631328, -35.261368), (-0.000001, -35.371094), (1.631327, -35.261368),
    (3.195912, -34.941727), (4.679437, -34.426492), (6.067587, -33.72998),
    (7.346042, -32.866504), (8.500488, -31.850388), (9.516605, -30.695941),
    (10.38008, -29.417487), (11.076592, -28.029337), (11.591827, -26.54581),
    (11.911468, -24.981226), (12.021196, -23.349899), (12.021196, 23.34673),
    (11.912133, 24.978119), (11.592928, 26.542877), (11.07793, 28.026663),
    (10.381488, 29.415137), (9.517953, 30.693964), (8.501676, 31.848804),
    (7.347005, 32.865314), (6.068291, 33.729156), (4.679883, 34.425998),
    (3.196132, 34.941492), (1.631388, 35.261304), (-0.000001, 35.371094),
    (-1.631328, 35.261368), (-3.195913, 34.941727), (-4.679439, 34.426492),
    (-6.067588, 33.72998), (-7.346043, 32.866504), (-8.500489, 31.850388),
    (-9.516607, 30.695941), (-10.380081, 29.417487), (-11.076594, 28.029337),
    (-11.591829, 26.54581), (-11.911469, 24.981226), (-12.021198, 23.349899),
    (-12.021198, -23.349899), (-11.911469, -24.981226), (-11.591829, -26.54581),
    (-11.076594, -28.029337), (-10.380081, -29.417487), (-9.516607, -30.695941),
    (-8.500489, -31.850388), (-7.346043, -32.866504), (-6.067588, -33.72998),
    (-4.679439, -34.426492), (-3.195913, -34.941727),
]

BASE_HOLE_COORDS = [
    (2.320331, 14.888806), (1.184381, 14.656863), (-0.000001, 14.577246),
    (-1.184382, 14.656924), (-2.320333, 14.889027), (-3.397453, 15.263155),
    (-4.405343, 15.768907), (-5.333604, 16.395886), (-6.171838, 17.133691),
    (-6.909644, 17.971924), (-7.536622, 18.900186), (-8.042375, 19.908076),
    (-8.416502, 20.985196), (-8.648605, 22.121147), (-8.728283, 23.305528),
    (-8.648605, 24.489909), (-8.416502, 25.625861), (-8.042375, 26.702982),
    (-7.536622, 27.71087), (-6.909644, 28.639133), (-6.171838, 29.477365),
    (-5.333604, 30.21517), (-4.405343, 30.842151), (-3.397453, 31.347903),
    (-2.320333, 31.722031), (-1.184382, 31.954132), (-0.000001, 32.03381),
    (1.184381, 31.954132), (2.320331, 31.722031), (3.397451, 31.347903),
    (4.405342, 30.842151), (5.333603, 30.21517), (6.171836, 29.477365),
    (6.909642, 28.639133), (7.536621, 27.71087), (8.042374, 26.702982),
    (8.416501, 25.625861), (8.648603, 24.489909), (8.728281, 23.305528),
    (8.648603, 22.12048), (8.416501, 20.984096), (8.042374, 19.90674),
    (7.536621, 18.898778), (6.909642, 17.970576), (6.171836, 17.132503),
    (5.333603, 16.394923), (4.405342, 15.768202), (3.397451, 15.262709),
]

BASE_POLYGON: sg.Polygon = sg.Polygon(BASE_OUTER_COORDS, [BASE_HOLE_COORDS]).buffer(0)

TOTAL_THICKNESS = 1.0
TEXT_THICKNESS = 0.6
TEXT_Z_MIN = TOTAL_THICKNESS - TEXT_THICKNESS  # 0.4 mm
TEXT_Z_MAX = TOTAL_THICKNESS                   # 1.0 mm
HOLE_BOTTOM_Y = 14.577246
HOLE_RIM_MM = 3.292915  # Spessore anello attorno al foro dal modello San_P_0.3mf (12.0212 - 8.7283)

MIN_WIDTH_MM = 20.0
MAX_WIDTH_MM = 30.0
DEFAULT_WIDTH_MM = 25.0

MIN_HEIGHT_MM = 60.0
MAX_HEIGHT_MM = 80.0
DEFAULT_HEIGHT_MM = 70.0

DEFAULT_BASE_COLOR = "#E03D19"
DEFAULT_TEXT_COLOR = "#FFFFFF"
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
class FontInfo:
    display_name: str
    path: str
    font_number: int = 0


@dataclass
class TagLayout:
    text: str
    lines: list[str]
    base_polygon: sg.Polygon
    usable_polygon: sg.Polygon
    text_polygon: sg.base.BaseGeometry
    font_scale_mm: float
    line_height_mm: float
    width_mm: float = DEFAULT_WIDTH_MM
    height_mm: float = DEFAULT_HEIGHT_MM


@dataclass
class TagMeshes:
    layout: TagLayout
    base_mesh: trimesh.Trimesh
    text_mesh: trimesh.Trimesh


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
    # Prefer English (Windows 3,1,0x409 or Mac/any) Full Name (nameID 4)
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

        # Calcola area con segno (shoelace) per distinguere contorni esterni e fori
        # rispettando la regola nonzero-winding usata da font con tratti sovrapposti (es. Bahnschrift).
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

        # Il contorno di area maggiore e' sempre un contorno esterno (pieno)
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


def _build_multiline_vertical_unit(
    lines: list[str],
    font_path: str,
    font_number: int = 0,
    line_spacing: float = 1.15,
) -> tuple[sg.base.BaseGeometry, float]:
    """
    Combina più righe e le ruota di -90° in senso orario come nel modello di riferimento:
    x_modello = +v_testo (alto delle lettere verso +X), y_modello = -u_testo (lettura dall'alto verso il basso).
    Restituisce (geometria_centrata_su_orig, altezza_singola_riga_in_unita_em).
    """
    rendered_lines: list[sg.base.BaseGeometry] = []
    line_heights: list[float] = []

    for idx, line in enumerate(lines):
        geom, _ = _layout_line_horizontal(line, font_path, font_number)
        if geom.is_empty:
            continue
        min_u, min_v, max_u, max_v = geom.bounds
        line_heights.append(max_v - min_v)
        # Centra ogni riga orizzontalmente (lungo u) rispetto alle altre righe
        u_mid = (min_u + max_u) * 0.5
        centered_u = sa.translate(geom, xoff=-u_mid, yoff=-idx * line_spacing)
        rendered_lines.append(centered_u)

    if not rendered_lines:
        return sg.GeometryCollection(), 0.72

    horiz = so.unary_union(rendered_lines).buffer(0)
    # Rotazione di -90 gradi: (u, v) -> (v, -u)
    vert = sa.rotate(horiz, -90.0, origin=(0.0, 0.0))
    minx, miny, maxx, maxy = vert.bounds
    cx = (minx + maxx) * 0.5
    cy = (miny + maxy) * 0.5
    vert = sa.translate(vert, xoff=-cx, yoff=-cy)
    avg_cap = float(np.mean(line_heights)) if line_heights else 0.72
    return vert, avg_cap


def build_base_polygon(
    width_mm: float = DEFAULT_WIDTH_MM,
    height_mm: float = DEFAULT_HEIGHT_MM,
) -> tuple[sg.Polygon, float, float, float]:
    """
    Costruisce la sagoma 2D parametrica della targhetta (capsula con foro superiore).
    Restituisce (poligono_base, hole_bottom_y, width_clamped, height_clamped).
    """
    w = float(np.clip(width_mm, MIN_WIDTH_MM, MAX_WIDTH_MM))
    h = float(np.clip(height_mm, MIN_HEIGHT_MM, MAX_HEIGHT_MM))
    r_outer = w * 0.5
    cy_cap = h * 0.5 - r_outer

    # Semicerchio inferiore (da pi a 2*pi) e superiore (da 0 a pi)
    angles_bot = np.linspace(np.pi, 2.0 * np.pi, 65)
    bot_pts = [(r_outer * float(np.cos(a)), -cy_cap + r_outer * float(np.sin(a))) for a in angles_bot]

    angles_top = np.linspace(0.0, np.pi, 65)
    top_pts = [(r_outer * float(np.cos(a)), cy_cap + r_outer * float(np.sin(a))) for a in angles_top]

    outer_pts = bot_pts + top_pts

    r_hole = max(1.0, r_outer - HOLE_RIM_MM)
    hole_angles = np.linspace(0.0, 2.0 * np.pi, 64, endpoint=False)
    hole_pts = [(r_hole * float(np.cos(a)), cy_cap + r_hole * float(np.sin(a))) for a in hole_angles]
    hole_bottom_y = cy_cap - r_hole

    poly = sg.Polygon(outer_pts, [hole_pts]).buffer(0)
    return poly, hole_bottom_y, w, h


def compute_usable_polygon(
    base_polygon: sg.Polygon | None = None,
    hole_bottom_y: float = HOLE_BOTTOM_Y,
    margin_mm: float = DEFAULT_MARGIN_MM,
) -> sg.base.BaseGeometry:
    """Calcola l'area utile sotto al foro rispettando il margine da bordo esterno e foro."""
    poly = base_polygon if base_polygon is not None else BASE_POLYGON
    margin_mm = max(0.3, min(margin_mm, 8.0))
    shrunk = poly.buffer(-margin_mm)
    minx, miny, maxx, _ = poly.bounds
    clip_box = sg.box(minx - 1.0, miny - 1.0, maxx + 1.0, hole_bottom_y - margin_mm)
    usable = shrunk.intersection(clip_box).buffer(0)
    return usable


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
            # Controlla se conviene inserire adesso o dopo
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


def _fit_unit_geometry(
    unit_geom: sg.base.BaseGeometry,
    usable: sg.base.BaseGeometry,
) -> tuple[sg.base.BaseGeometry, float]:
    """Trova per bisezione la scala massima (mm per 1 EM) che sta interamente in `usable`."""
    if unit_geom.is_empty or usable.is_empty:
        return sg.GeometryCollection(), 0.0

    uminx, uminy, umaxx, umaxy = usable.bounds
    target_cx = (uminx + umaxx) * 0.5
    target_cy = (uminy + umaxy) * 0.5

    # Piccola tolleranza di area per robustezza numerica sui vertici curvi
    lo, hi = 0.2, 45.0
    best_scale = lo
    best_geom = sa.translate(sa.scale(unit_geom, xfact=lo, yfact=lo, origin=(0.0, 0.0)), xoff=target_cx, yoff=target_cy)

    for _ in range(26):
        mid = (lo + hi) * 0.5
        cand = sa.scale(unit_geom, xfact=mid, yfact=mid, origin=(0.0, 0.0))
        cand = sa.translate(cand, xoff=target_cx, yoff=target_cy)
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
    width_mm: float = DEFAULT_WIDTH_MM,
    height_mm: float = DEFAULT_HEIGHT_MM,
) -> TagLayout:
    """Calcola layout, eventuale a capo automatico e dimensione ottimale del testo."""
    base_poly, hole_bottom_y, w_clamped, h_clamped = build_base_polygon(width_mm, height_mm)
    usable = compute_usable_polygon(base_poly, hole_bottom_y, margin_mm)
    raw = text.replace("\r\n", "\n").strip("\n")

    if not raw.strip():
        return TagLayout(
            text=text,
            lines=[],
            base_polygon=base_poly,
            usable_polygon=usable,
            text_polygon=sg.GeometryCollection(),
            font_scale_mm=0.0,
            line_height_mm=0.0,
            width_mm=w_clamped,
            height_mm=h_clamped,
        )

    manual_lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]

    if len(manual_lines) > 1 or wrap_mode == "single":
        lines = manual_lines
        unit_geom, avg_cap = _build_multiline_vertical_unit(lines, font_path, font_number, line_spacing)
        fitted, scale = _fit_unit_geometry(unit_geom, usable)
        return TagLayout(
            text=text,
            lines=lines,
            base_polygon=base_poly,
            usable_polygon=usable,
            text_polygon=fitted,
            font_scale_mm=scale,
            line_height_mm=scale * avg_cap,
            width_mm=w_clamped,
            height_mm=h_clamped,
        )

    # Modalita' auto: prova prima su 1 riga; se diventa troppo piccola, prova 2..4 righe
    single_line = manual_lines[0]
    unit1, cap1 = _build_multiline_vertical_unit([single_line], font_path, font_number, line_spacing)
    fit1, scale1 = _fit_unit_geometry(unit1, usable)
    height1 = scale1 * cap1

    words = single_line.split()
    if height1 >= AUTO_WRAP_MIN_LINE_HEIGHT_MM or len(words) <= 1:
        return TagLayout(
            text=text,
            lines=[single_line],
            base_polygon=base_poly,
            usable_polygon=usable,
            text_polygon=fit1,
            font_scale_mm=scale1,
            line_height_mm=height1,
            width_mm=w_clamped,
            height_mm=h_clamped,
        )

    best_lines = [single_line]
    best_fit = fit1
    best_scale = scale1
    best_height = height1

    max_k = min(4, len(words))
    for k in range(2, max_k + 1):
        cand_lines = _wrap_words_into_k_lines(words, k)
        if len(cand_lines) <= 1:
            continue
        unit_k, cap_k = _build_multiline_vertical_unit(cand_lines, font_path, font_number, line_spacing)
        fit_k, scale_k = _fit_unit_geometry(unit_k, usable)
        height_k = scale_k * cap_k
        if height_k > best_height * 1.03:
            best_lines = cand_lines
            best_fit = fit_k
            best_scale = scale_k
            best_height = height_k

    return TagLayout(
        text=text,
        lines=best_lines,
        base_polygon=base_poly,
        usable_polygon=usable,
        text_polygon=best_fit,
        font_scale_mm=best_scale,
        line_height_mm=best_height,
        width_mm=w_clamped,
        height_mm=h_clamped,
    )


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


def _polygon_to_2d_tris(poly: sg.Polygon) -> tuple[np.ndarray, np.ndarray]:
    if poly.is_empty or poly.area < 1e-8:
        return np.zeros((0, 2)), np.zeros((0, 3), dtype=np.int64)
    ext = np.asarray(poly.exterior.coords)[:-1, :2]
    rings = [ext]
    hole_starts: list[int] = []
    idx = len(ext)
    for interior in poly.interiors:
        hole = np.asarray(interior.coords)[:-1, :2]
        if len(hole) >= 3:
            hole_starts.append(idx)
            rings.append(hole)
            idx += len(hole)
    verts_2d = np.vstack(rings)
    ring_ends = np.array(hole_starts + [len(verts_2d)], dtype=np.uint32)
    tris = mapbox_earcut.triangulate_float64(verts_2d, ring_ends).reshape(-1, 3)
    return verts_2d, tris


def _build_cap(geom: sg.base.BaseGeometry, z: float, flip_normal: bool) -> tuple[np.ndarray, np.ndarray]:
    all_v: list[np.ndarray] = []
    all_f: list[np.ndarray] = []
    offset = 0
    for poly in _geom_to_polys(geom):
        v2, f = _polygon_to_2d_tris(poly)
        if len(f) == 0:
            continue
        v3 = np.column_stack([v2, np.full(len(v2), z)])
        a, b, c = v2[f[:, 0]], v2[f[:, 1]], v2[f[:, 2]]
        cross = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
        f = np.where(cross[:, None] < 0, f[:, [0, 2, 1]], f)
        if flip_normal:
            f = f[:, [0, 2, 1]]
        all_v.append(v3)
        all_f.append(f + offset)
        offset += len(v3)
    if not all_v:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    return np.vstack(all_v), np.vstack(all_f)


def _build_walls(ring_coords, z0: float, z1: float, outward_ccw: bool) -> tuple[np.ndarray, np.ndarray]:
    pts = np.asarray(ring_coords)[:, :2]
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    x, y = pts[:, 0], pts[:, 1]
    area2 = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    is_ccw = area2 > 0
    if is_ccw != outward_ccw:
        pts = pts[::-1]
    v_bot = np.column_stack([pts, np.full(n, z0)])
    v_top = np.column_stack([pts, np.full(n, z1)])
    verts = np.vstack([v_bot, v_top])
    idx = np.arange(n, dtype=np.int64)
    nxt = (idx + 1) % n
    f1 = np.column_stack([idx, nxt, n + nxt])
    f2 = np.column_stack([idx, n + nxt, n + idx])
    return verts, np.vstack([f1, f2])


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


def build_tag_meshes(layout: TagLayout) -> TagMeshes:
    """
    Genera le 2 mesh 3D non sovrapposte e chiuse (watertight):
    - `base_mesh`: Z in [0.0, 1.0], con sede incassata Z in [0.4, 1.0] dove cade il testo.
    - `text_mesh`: Z in [0.4, 1.0], a filo con la faccia frontale Z = 1.0.
    """
    B = layout.base_polygon.buffer(0)
    T = layout.text_polygon.buffer(0) if not layout.text_polygon.is_empty else sg.GeometryCollection()

    if T.is_empty:
        base_mesh = trimesh.creation.extrude_polygon(B, height=TOTAL_THICKNESS)
        return TagMeshes(layout=layout, base_mesh=base_mesh, text_mesh=trimesh.Trimesh())

    # Rimuove eventuali micropoli degeneri e vertici collineari (evita T-junction in earcut)
    t_polys = _geom_to_polys(T)
    T = so.unary_union(t_polys).simplify(1e-6, preserve_topology=True).buffer(0) if t_polys else sg.GeometryCollection()
    R = B.difference(T).buffer(0)

    # Mesh testo: prisma Z in [0.4, 1.0]
    t_parts = [
        _build_cap(T, TEXT_Z_MIN, flip_normal=True),
        _build_cap(T, TEXT_Z_MAX, flip_normal=False),
    ]
    for p in _geom_to_polys(T):
        t_parts.append(_build_walls(p.exterior.coords, TEXT_Z_MIN, TEXT_Z_MAX, outward_ccw=True))
        for h in p.interiors:
            t_parts.append(_build_walls(h.coords, TEXT_Z_MIN, TEXT_Z_MAX, outward_ccw=False))
    text_mesh = _combine_mesh_parts(t_parts)

    # Mesh base a gradino 2.5D senza sovrapposizioni ne' facce interne a Z=0.4
    b_parts = [
        _build_cap(B, 0.0, flip_normal=True),
        _build_cap(R, TOTAL_THICKNESS, flip_normal=False),
        _build_cap(T, TEXT_Z_MIN, flip_normal=False),
    ]
    for p in _geom_to_polys(B):
        b_parts.append(_build_walls(p.exterior.coords, 0.0, TOTAL_THICKNESS, outward_ccw=True))
        for h in p.interiors:
            b_parts.append(_build_walls(h.coords, 0.0, TOTAL_THICKNESS, outward_ccw=False))
    for p in _geom_to_polys(T):
        b_parts.append(_build_walls(p.exterior.coords, TEXT_Z_MIN, TEXT_Z_MAX, outward_ccw=False))
        for h in p.interiors:
            b_parts.append(_build_walls(h.coords, TEXT_Z_MIN, TEXT_Z_MAX, outward_ccw=True))
    base_mesh = _combine_mesh_parts(b_parts)

    return TagMeshes(layout=layout, base_mesh=base_mesh, text_mesh=text_mesh)


def _to_face_down_plate(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Ruota di 180 gradi attorno a Y (-x, y, 1 - z) cosi' il testo poggia sul piatto a Z=0."""
    if len(mesh.vertices) == 0:
        return mesh
    m = mesh.copy()
    v = m.vertices.copy()
    v[:, 0] = -v[:, 0]
    v[:, 2] = TOTAL_THICKNESS - v[:, 2]
    m.vertices = v
    # Nota: x -> -x e z -> -z (det = +1), l'orientamento delle facce rimane invariato
    return m


def export_stls(meshes: TagMeshes, out_dir: Path, base_stem: str) -> tuple[Path, Path | None]:
    """Esporta 2 file STL separati (base e testo) orientati face-down pronti per il piatto."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base_path = out_dir / f"{base_stem}_base.stl"
    text_path = out_dir / f"{base_stem}_testo.stl"

    base_plate = _to_face_down_plate(meshes.base_mesh)
    base_plate.export(str(base_path))

    if len(meshes.text_mesh.vertices) > 0:
        text_plate = _to_face_down_plate(meshes.text_mesh)
        text_plate.export(str(text_path))
        return base_path, text_path
    return base_path, None


def render_thumbnail_png(
    layout: TagLayout,
    base_color: str = DEFAULT_BASE_COLOR,
    text_color: str = DEFAULT_TEXT_COLOR,
    size: tuple[int, int] = (320, 553),
) -> bytes:
    """Renderizza un'anteprima PNG ad alta qualità (usata sia per la miniatura 3MF che per export)."""
    w, h = size
    scale = 4  # supersampling 4x per bordi nitidi
    W, H = w * scale, h * scale
    img = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Adatta la targhetta dentro (W, H) con padding simile a San_P_0.3mf
    mm_scale = min((W * 0.44) / max(layout.width_mm, 1.0), (H * 0.68) / max(layout.height_mm, 1.0))
    cx, cy = W * 0.5, H * 0.5

    def to_px(coords):
        return [(cx + x * mm_scale, cy - y * mm_scale) for x, y in coords]

    def draw_geom(geom: sg.base.BaseGeometry, fill_color: str, hole_color: tuple[int, int, int, int]):
        for poly in _geom_to_polys(geom):
            draw.polygon(to_px(poly.exterior.coords), fill=fill_color)
            for hole in poly.interiors:
                draw.polygon(to_px(hole.coords), fill=hole_color)

    draw_geom(layout.base_polygon, base_color, (255, 255, 255, 0))
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
        f'    <item objectid="29" p:uuid="{u_item}" transform="-1 0 0 0 1 0 0 0 -1 90 70 1" printable="1"/>\n'
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
