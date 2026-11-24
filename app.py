"""
Interfaccia grafica desktop (Tkinter) per il generatore di etichette 3D.
"""

from __future__ import annotations

import csv
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

import tag_generator as tg


class TagApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Generatore Targhette 3D (.3MF / .STL)")
        self.geometry("1020x700")
        self.minsize(900, 620)

        self.fonts = tg.discover_system_fonts()
        default_font = tg.pick_default_font(self.fonts)

        self.custom_font_path: str | None = None
        self.base_color = tg.DEFAULT_BASE_COLOR
        self.text_color = tg.DEFAULT_TEXT_COLOR
        self.current_layout: tg.TagLayout | None = None
        self._preview_after_id: str | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._batch_running = False

        self.var_font_name = tk.StringVar(value=default_font.display_name if default_font else "")
        self.var_wrap_mode = tk.StringVar(value="auto")
        self.var_width = tk.DoubleVar(value=tg.DEFAULT_WIDTH_MM)
        self.var_height = tk.DoubleVar(value=tg.DEFAULT_HEIGHT_MM)
        self.var_margin = tk.DoubleVar(value=tg.DEFAULT_MARGIN_MM)
        self.var_show_usable = tk.BooleanVar(value=True)
        self.var_status = tk.StringVar(value="Pronto")
        self.var_metrics = tk.StringVar(value="")
        self.var_specs = tk.StringVar(
            value=f"Dimensioni: {tg.DEFAULT_HEIGHT_MM:.1f} x {tg.DEFAULT_WIDTH_MM:.1f} mm | Base: 1.0 mm | Testo a filo: 0.6 mm (face-down)"
        )

        # Variabili batch
        default_out = str(Path.cwd() / "output_targhette")
        self.var_batch_dir = tk.StringVar(value=default_out)
        self.var_batch_3mf = tk.BooleanVar(value=True)
        self.var_batch_stl = tk.BooleanVar(value=False)

        self._build_ui()
        self._schedule_preview()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1, minsize=470)
        self.columnconfigure(1, weight=1, minsize=380)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=12)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        notebook = ttk.Notebook(left)
        notebook.grid(row=0, column=0, sticky="nsew")

        tab_single = ttk.Frame(notebook, padding=10)
        tab_batch = ttk.Frame(notebook, padding=10)
        notebook.add(tab_single, text="  Etichetta Singola  ")
        notebook.add(tab_batch, text="  Generazione Multipla  ")

        self._build_single_tab(tab_single)
        self._build_batch_tab(tab_batch)

        # Barra impostazioni comuni (Font, Colori, Margine)
        common = ttk.LabelFrame(left, text="Stile e Parametri Modello", padding=10)
        common.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._build_common_settings(common)

        # Status bar in basso a sinistra
        status_lbl = ttk.Label(left, textvariable=self.var_status, foreground="#444444")
        status_lbl.grid(row=2, column=0, sticky="w", pady=(8, 0))

        # Colonna destra: Anteprima
        right = ttk.LabelFrame(self, text="Anteprima Frontale (scala reale)", padding=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.preview_label = ttk.Label(right, anchor="center", background="#F4F4F6")
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        self.preview_label.bind("<Configure>", lambda _e: self._render_preview_image())

        info_lbl = ttk.Label(right, textvariable=self.var_metrics, justify="center", foreground="#333333")
        info_lbl.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        spec_lbl = ttk.Label(
            right,
            textvariable=self.var_specs,
            foreground="#666666",
            font=("Segoe UI", 8),
            anchor="center",
        )
        spec_lbl.grid(row=2, column=0, sticky="ew", pady=(2, 0))

    def _build_single_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        ttk.Label(parent, text="Testo dell'etichetta (premi Invio per andare a capo manualmente):").grid(
            row=0, column=0, sticky="w"
        )
        self.txt_single = tk.Text(parent, height=4, font=("Segoe UI", 12), wrap="word")
        self.txt_single.insert("1.0", "ABUS LUCH.")
        self.txt_single.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        self.txt_single.bind("<KeyRelease>", lambda _e: self._schedule_preview())

        wrap_frame = ttk.Frame(parent)
        wrap_frame.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(wrap_frame, text="Adattamento testo:").pack(side="left")
        ttk.Radiobutton(
            wrap_frame,
            text="Auto (a capo se lungo)",
            variable=self.var_wrap_mode,
            value="auto",
            command=self._schedule_preview,
        ).pack(side="left", padx=(10, 8))
        ttk.Radiobutton(
            wrap_frame,
            text="Riga singola",
            variable=self.var_wrap_mode,
            value="single",
            command=self._schedule_preview,
        ).pack(side="left")

        btns = ttk.LabelFrame(parent, text="Esportazione Singola", padding=10)
        btns.grid(row=3, column=0, sticky="ew")
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        ttk.Button(
            btns,
            text="Salva .3MF (Multi-colore)",
            command=self._export_single_3mf,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=3)

        ttk.Button(
            btns,
            text="Salva 2 .STL (Base + Testo)",
            command=self._export_single_stls,
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=3)

        ttk.Button(
            btns,
            text="Salva Entrambi (.3MF + 2 .STL in cartella)",
            command=self._export_single_both,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 2))

    def _build_batch_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Una targhetta per riga (usa '|' per forzare a capo):").pack(side="left")
        ttk.Button(top, text="Carica TXT/CSV...", command=self._load_batch_file).pack(side="right")

        self.txt_batch = tk.Text(parent, height=8, font=("Consolas", 10))
        self.txt_batch.insert("1.0", "ABUS LUCH.\nCANCELLO NORD\nGARAGE|PRINCIPALE\nCANTINA")
        self.txt_batch.grid(row=1, column=0, sticky="nsew", pady=(6, 8))

        fmt_frame = ttk.Frame(parent)
        fmt_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(fmt_frame, text="Formati:").pack(side="left")
        ttk.Checkbutton(fmt_frame, text="File .3MF", variable=self.var_batch_3mf).pack(side="left", padx=(10, 8))
        ttk.Checkbutton(fmt_frame, text="2 File .STL (base + testo)", variable=self.var_batch_stl).pack(side="left")

        dir_frame = ttk.Frame(parent)
        dir_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        dir_frame.columnconfigure(0, weight=1)
        ttk.Entry(dir_frame, textvariable=self.var_batch_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(dir_frame, text="Cartella...", command=self._choose_batch_dir).grid(row=0, column=1)

        self.batch_progress = ttk.Progressbar(parent, mode="determinate")
        self.batch_progress.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        self.btn_run_batch = ttk.Button(
            parent,
            text="Genera Tutte le Targhette",
            command=self._run_batch,
        )
        self.btn_run_batch.grid(row=5, column=0, sticky="ew")

    def _build_common_settings(self, parent: ttk.LabelFrame) -> None:
        parent.columnconfigure(1, weight=1)

        # Font selector
        ttk.Label(parent, text="Font:").grid(row=0, column=0, sticky="w", pady=3)
        font_names = [f.display_name for f in self.fonts]
        self.cmb_font = ttk.Combobox(parent, textvariable=self.var_font_name, values=font_names, state="readonly")
        self.cmb_font.grid(row=0, column=1, sticky="ew", padx=(8, 6), pady=3)
        self.cmb_font.bind("<<ComboboxSelected>>", self._on_system_font_selected)
        ttk.Button(parent, text="File .ttf/.otf...", command=self._browse_custom_font).grid(row=0, column=2, pady=3)

        # Colori
        ttk.Label(parent, text="Colori 3MF:").grid(row=1, column=0, sticky="w", pady=4)
        col_frame = ttk.Frame(parent)
        col_frame.grid(row=1, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=4)

        self.btn_base_col = tk.Button(
            col_frame,
            text=f" Base {self.base_color} ",
            bg=self.base_color,
            fg="#FFFFFF",
            relief="groove",
            command=self._pick_base_color,
        )
        self.btn_base_col.pack(side="left", padx=(0, 8))

        self.btn_text_col = tk.Button(
            col_frame,
            text=f" Testo {self.text_color} ",
            bg=self.text_color,
            fg="#111111",
            relief="groove",
            command=self._pick_text_color,
        )
        self.btn_text_col.pack(side="left", padx=(0, 8))

        ttk.Button(col_frame, text="Ripristina", command=self._reset_colors).pack(side="left")

        # Dimensioni (Altezza 60-80 mm, Larghezza 20-30 mm)
        ttk.Label(parent, text="Dimensioni (mm):").grid(row=2, column=0, sticky="w", pady=3)
        dim_frame = ttk.Frame(parent)
        dim_frame.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3)
        dim_frame.columnconfigure(1, weight=1)
        dim_frame.columnconfigure(4, weight=1)

        ttk.Label(dim_frame, text="V:").grid(row=0, column=0, sticky="w")
        sc_h = ttk.Scale(
            dim_frame,
            from_=tg.MIN_HEIGHT_MM,
            to=tg.MAX_HEIGHT_MM,
            variable=self.var_height,
            command=lambda _v: self._on_dimension_slider(),
        )
        sc_h.grid(row=0, column=1, sticky="ew", padx=(4, 4))
        sp_h = ttk.Spinbox(
            dim_frame,
            from_=tg.MIN_HEIGHT_MM,
            to=tg.MAX_HEIGHT_MM,
            increment=0.5,
            textvariable=self.var_height,
            width=5,
            command=self._schedule_preview,
        )
        sp_h.grid(row=0, column=2, padx=(0, 8))
        sp_h.bind("<KeyRelease>", lambda _e: self._schedule_preview())
        sp_h.bind("<FocusOut>", lambda _e: self._clamp_dimensions())

        ttk.Label(dim_frame, text="O:").grid(row=0, column=3, sticky="w")
        sc_w = ttk.Scale(
            dim_frame,
            from_=tg.MIN_WIDTH_MM,
            to=tg.MAX_WIDTH_MM,
            variable=self.var_width,
            command=lambda _v: self._on_dimension_slider(),
        )
        sc_w.grid(row=0, column=4, sticky="ew", padx=(4, 4))
        sp_w = ttk.Spinbox(
            dim_frame,
            from_=tg.MIN_WIDTH_MM,
            to=tg.MAX_WIDTH_MM,
            increment=0.5,
            textvariable=self.var_width,
            width=5,
            command=self._schedule_preview,
        )
        sp_w.grid(row=0, column=5, padx=(0, 6))
        sp_w.bind("<KeyRelease>", lambda _e: self._schedule_preview())
        sp_w.bind("<FocusOut>", lambda _e: self._clamp_dimensions())

        ttk.Button(dim_frame, text="70x25", width=6, command=self._reset_dimensions).grid(row=0, column=6)

        # Margine
        ttk.Label(parent, text="Margine (mm):").grid(row=3, column=0, sticky="w", pady=3)
        m_frame = ttk.Frame(parent)
        m_frame.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3)
        m_frame.columnconfigure(0, weight=1)

        scale = ttk.Scale(
            m_frame,
            from_=1.0,
            to=5.0,
            variable=self.var_margin,
            command=lambda _v: self._on_margin_changed(),
        )
        scale.grid(row=0, column=0, sticky="ew")
        self.lbl_margin_val = ttk.Label(m_frame, text=f"{self.var_margin.get():.1f} mm", width=7)
        self.lbl_margin_val.grid(row=0, column=1, padx=(6, 8))
        ttk.Checkbutton(
            m_frame,
            text="Mostra area utile",
            variable=self.var_show_usable,
            command=self._render_preview_image,
        ).grid(row=0, column=2)

    def _active_font(self) -> tuple[str, int]:
        if self.custom_font_path:
            return self.custom_font_path, 0
        sel = self.var_font_name.get()
        for f in self.fonts:
            if f.display_name == sel:
                return f.path, f.font_number
        if self.fonts:
            return self.fonts[0].path, self.fonts[0].font_number
        raise RuntimeError("Nessun font TTF/OTF disponibile nel sistema.")

    def _on_system_font_selected(self, _evt=None) -> None:
        self.custom_font_path = None
        self._schedule_preview()

    def _browse_custom_font(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleziona un file font (.ttf / .otf)",
            filetypes=[("Font files", "*.ttf *.otf"), ("All files", "*.*")],
        )
        if not path:
            return
        self.custom_font_path = path
        self.var_font_name.set(f"[Custom] {Path(path).name}")
        self._schedule_preview()

    def _contrast_fg(self, hex_color: str) -> str:
        c = hex_color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return "#111111" if lum > 145 else "#FFFFFF"

    def _pick_base_color(self) -> None:
        _, hx = colorchooser.askcolor(color=self.base_color, title="Colore Etichetta")
        if hx:
            self.base_color = hx.upper()
            self.btn_base_col.configure(
                text=f" Base {self.base_color} ",
                bg=self.base_color,
                fg=self._contrast_fg(self.base_color),
            )
            self._render_preview_image()

    def _pick_text_color(self) -> None:
        _, hx = colorchooser.askcolor(color=self.text_color, title="Colore Testo")
        if hx:
            self.text_color = hx.upper()
            self.btn_text_col.configure(
                text=f" Testo {self.text_color} ",
                bg=self.text_color,
                fg=self._contrast_fg(self.text_color),
            )
            self._render_preview_image()

    def _reset_colors(self) -> None:
        self.base_color = tg.DEFAULT_BASE_COLOR
        self.text_color = tg.DEFAULT_TEXT_COLOR
        self.btn_base_col.configure(text=f" Base {self.base_color} ", bg=self.base_color, fg="#FFFFFF")
        self.btn_text_col.configure(text=f" Testo {self.text_color} ", bg=self.text_color, fg="#111111")
        self._render_preview_image()

    def _get_dimensions(self) -> tuple[float, float]:
        try:
            w = float(self.var_width.get())
        except (tk.TclError, ValueError):
            w = tg.DEFAULT_WIDTH_MM
        try:
            h = float(self.var_height.get())
        except (tk.TclError, ValueError):
            h = tg.DEFAULT_HEIGHT_MM
        w = max(tg.MIN_WIDTH_MM, min(tg.MAX_WIDTH_MM, round(w, 1)))
        h = max(tg.MIN_HEIGHT_MM, min(tg.MAX_HEIGHT_MM, round(h, 1)))
        return w, h

    def _on_dimension_slider(self) -> None:
        w, h = self._get_dimensions()
        self.var_width.set(w)
        self.var_height.set(h)
        self._schedule_preview()

    def _clamp_dimensions(self) -> None:
        w, h = self._get_dimensions()
        self.var_width.set(w)
        self.var_height.set(h)
        self._schedule_preview()

    def _reset_dimensions(self) -> None:
        self.var_width.set(tg.DEFAULT_WIDTH_MM)
        self.var_height.set(tg.DEFAULT_HEIGHT_MM)
        self._schedule_preview()

    def _on_margin_changed(self) -> None:
        val = round(self.var_margin.get(), 1)
        self.lbl_margin_val.configure(text=f"{val:.1f} mm")
        self._schedule_preview()

    def _schedule_preview(self) -> None:
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(100, self._update_layout_and_preview)

    def _update_layout_and_preview(self) -> None:
        self._preview_after_id = None
        text = self.txt_single.get("1.0", "end-1c")
        try:
            fpath, fnum = self._active_font()
            margin = round(float(self.var_margin.get()), 2)
            width_mm, height_mm = self._get_dimensions()
            layout = tg.compute_tag_layout(
                text=text,
                font_path=fpath,
                font_number=fnum,
                margin_mm=margin,
                wrap_mode=self.var_wrap_mode.get(),
                width_mm=width_mm,
                height_mm=height_mm,
            )
            self.current_layout = layout
            self.var_specs.set(
                f"Dimensioni: {layout.height_mm:.1f} x {layout.width_mm:.1f} mm | Base: 1.0 mm | Testo a filo: 0.6 mm (face-down)"
            )
            if layout.lines:
                self.var_metrics.set(
                    f"Righe: {len(layout.lines)}  |  Altezza carattere: {layout.line_height_mm:.2f} mm  |  Margine: {margin:.1f} mm"
                )
            else:
                self.var_metrics.set("Inserisci un testo per vedere l'anteprima")
            self.var_status.set("Anteprima aggiornata")
        except Exception as exc:
            self.var_status.set(f"Errore font/layout: {exc}")
            return

        self._render_preview_image()

    def _render_preview_image(self) -> None:
        layout = self.current_layout
        if layout is None:
            return
        w = max(self.preview_label.winfo_width(), 320)
        h = max(self.preview_label.winfo_height(), 460)

        ss = 2
        W, H = w * ss, h * ss
        img = Image.new("RGBA", (W, H), (244, 244, 246, 255))
        draw = ImageDraw.Draw(img)

        mm_scale = min((W * 0.78) / max(layout.width_mm, 1.0), (H * 0.88) / max(layout.height_mm, 1.0))
        cx, cy = W * 0.5, H * 0.5

        def to_px(coords):
            return [(cx + x * mm_scale, cy - y * mm_scale) for x, y in coords]

        def draw_geom(geom, fill_color, hole_color):
            for poly in tg._geom_to_polys(geom):
                draw.polygon(to_px(poly.exterior.coords), fill=fill_color)
                for hole in poly.interiors:
                    draw.polygon(to_px(hole.coords), fill=hole_color)

        draw_geom(layout.base_polygon, self.base_color, (244, 244, 246, 255))

        if self.var_show_usable.get() and not layout.usable_polygon.is_empty:
            for poly in tg._geom_to_polys(layout.usable_polygon):
                pts = to_px(poly.exterior.coords)
                for i in range(0, len(pts) - 1, 2):
                    draw.line([pts[i], pts[i + 1]], fill=(255, 255, 255, 160), width=max(1, ss))

        if not layout.text_polygon.is_empty:
            draw_geom(layout.text_polygon, self.text_color, self.base_color)

        img = img.resize((w, h), Image.Resampling.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(img)
        self.preview_label.configure(image=self._preview_photo)

    def _build_current_meshes(self) -> tg.TagMeshes | None:
        self._update_layout_and_preview()
        if self.current_layout is None:
            return None
        if not self.current_layout.lines:
            messagebox.showwarning("Testo vuoto", "Inserisci almeno un carattere prima di esportare.")
            return None
        self.var_status.set("Generazione mesh 3D in corso...")
        self.update_idletasks()
        return tg.build_tag_meshes(self.current_layout)

    def _export_single_3mf(self) -> None:
        meshes = self._build_current_meshes()
        if meshes is None:
            return
        stem = tg.sanitize_filename(meshes.layout.text)
        out_path = filedialog.asksaveasfilename(
            title="Salva file .3MF multi-colore",
            defaultextension=".3mf",
            initialfile=f"{stem}.3mf",
            filetypes=[("3MF files", "*.3mf")],
        )
        if not out_path:
            return
        try:
            tg.export_3mf(
                meshes,
                Path(out_path),
                base_color=self.base_color,
                text_color=self.text_color,
                title=Path(out_path).stem,
            )
            self.var_status.set(f"Salvato: {Path(out_path).name}")
            messagebox.showinfo("Esportazione completata", f"File 3MF salvato in:\n{out_path}")
        except Exception as exc:
            messagebox.showerror("Errore esportazione", str(exc))

    def _export_single_stls(self) -> None:
        meshes = self._build_current_meshes()
        if meshes is None:
            return
        stem = tg.sanitize_filename(meshes.layout.text)
        out_dir = filedialog.askdirectory(title="Scegli la cartella dove salvare i 2 file STL")
        if not out_dir:
            return
        try:
            base_p, text_p = tg.export_stls(meshes, Path(out_dir), stem)
            msg = f"Salvati:\n- {base_p.name}"
            if text_p:
                msg += f"\n- {text_p.name}"
            self.var_status.set(f"STL salvati in {Path(out_dir).name}")
            messagebox.showinfo("Esportazione completata", msg)
        except Exception as exc:
            messagebox.showerror("Errore esportazione", str(exc))

    def _export_single_both(self) -> None:
        meshes = self._build_current_meshes()
        if meshes is None:
            return
        stem = tg.sanitize_filename(meshes.layout.text)
        out_dir = filedialog.askdirectory(title="Scegli la cartella dove salvare .3MF e i 2 .STL")
        if not out_dir:
            return
        try:
            out_folder = Path(out_dir)
            p_3mf = tg.export_3mf(
                meshes,
                out_folder / f"{stem}.3mf",
                base_color=self.base_color,
                text_color=self.text_color,
                title=stem,
            )
            p_base, p_text = tg.export_stls(meshes, out_folder, stem)
            self.var_status.set(f"Esportati 3MF + STL in {out_folder.name}")
            messagebox.showinfo(
                "Esportazione completata",
                f"File salvati in {out_folder}:\n- {p_3mf.name}\n- {p_base.name}"
                + (f"\n- {p_text.name}" if p_text else ""),
            )
        except Exception as exc:
            messagebox.showerror("Errore esportazione", str(exc))

    def _load_batch_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Carica lista etichette (.txt o .csv)",
            filetypes=[("Text/CSV", "*.txt *.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        p = Path(path)
        lines: list[str] = []
        if p.suffix.lower() == ".csv":
            with p.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip():
                        lines.append(row[0].strip())
        else:
            with p.open("r", encoding="utf-8-sig") as f:
                for ln in f:
                    if ln.strip():
                        lines.append(ln.strip())
        self.txt_batch.delete("1.0", "end")
        self.txt_batch.insert("1.0", "\n".join(lines))

    def _choose_batch_dir(self) -> None:
        d = filedialog.askdirectory(title="Cartella di destinazione")
        if d:
            self.var_batch_dir.set(d)

    def _run_batch(self) -> None:
        if self._batch_running:
            return
        if not self.var_batch_3mf.get() and not self.var_batch_stl.get():
            messagebox.showwarning("Nessun formato", "Seleziona almeno un formato (.3MF o .STL).")
            return
        raw_lines = [ln.strip() for ln in self.txt_batch.get("1.0", "end-1c").splitlines() if ln.strip()]
        if not raw_lines:
            messagebox.showwarning("Lista vuota", "Inserisci almeno una riga nella lista.")
            return

        out_dir = Path(self.var_batch_dir.get().strip() or "output_targhette")
        try:
            fpath, fnum = self._active_font()
        except Exception as exc:
            messagebox.showerror("Errore font", str(exc))
            return

        margin = round(float(self.var_margin.get()), 2)
        width_mm, height_mm = self._get_dimensions()
        wrap_mode = self.var_wrap_mode.get()
        do_3mf = self.var_batch_3mf.get()
        do_stl = self.var_batch_stl.get()
        b_col = self.base_color
        t_col = self.text_color

        self._batch_running = True
        self.btn_run_batch.configure(state="disabled")
        self.batch_progress.configure(maximum=len(raw_lines), value=0)

        def worker():
            used_stems: dict[str, int] = {}
            errors: list[str] = []
            created = 0
            for idx, item in enumerate(raw_lines, start=1):
                label_text = item.replace("|", "\n").replace("\\n", "\n")
                stem = tg.sanitize_filename(label_text)
                count = used_stems.get(stem, 0) + 1
                used_stems[stem] = count
                unique_stem = stem if count == 1 else f"{stem}_{count}"
                try:
                    lay = tg.compute_tag_layout(
                        text=label_text,
                        font_path=fpath,
                        font_number=fnum,
                        margin_mm=margin,
                        wrap_mode=wrap_mode,
                        width_mm=width_mm,
                        height_mm=height_mm,
                    )
                    meshes = tg.build_tag_meshes(lay)
                    if do_3mf:
                        tg.export_3mf(
                            meshes,
                            out_dir / f"{unique_stem}.3mf",
                            base_color=b_col,
                            text_color=t_col,
                            title=unique_stem,
                        )
                    if do_stl:
                        tg.export_stls(meshes, out_dir, unique_stem)
                    created += 1
                except Exception as exc:
                    errors.append(f"{item!r}: {exc}")

                self.after(0, lambda v=idx, t=item: self._on_batch_step(v, len(raw_lines), t))

            self.after(0, lambda: self._on_batch_done(created, out_dir, errors))

        threading.Thread(target=worker, daemon=True).start()

    def _on_batch_step(self, done: int, total: int, item: str) -> None:
        self.batch_progress.configure(value=done)
        self.var_status.set(f"Batch {done}/{total}: {item}")

    def _on_batch_done(self, created: int, out_dir: Path, errors: list[str]) -> None:
        self._batch_running = False
        self.btn_run_batch.configure(state="normal")
        if errors:
            self.var_status.set(f"Completato con {len(errors)} errori")
            messagebox.showwarning(
                "Batch completato con avvisi",
                f"Generate {created} targhette in:\n{out_dir}\n\nErrori:\n" + "\n".join(errors[:5]),
            )
        else:
            self.var_status.set(f"Batch completato: {created} targhette")
            messagebox.showinfo(
                "Batch completato",
                f"Generate con successo {created} targhette in:\n{out_dir}",
            )


def main() -> None:
    app = TagApp()
    app.mainloop()


if __name__ == "__main__":
    main()
