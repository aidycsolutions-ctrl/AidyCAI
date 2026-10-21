from __future__ import annotations

import json
import os
import queue
import threading
import traceback
import webbrowser
from tkinter import ttk, messagebox
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from aidycai.application.bootstrap import open_app
from aidycai.application.diagnostics import render_diagnosis, render_human_answer
from aidycai.domain.context_models import ContextBundle, ROLE_PRIMARY
from aidycai.application.defaults import DEFAULT_PROJECTS
from aidycai.application.project_config import get_project_config
from aidycai.application.project_actions import ProjectActions
from aidycai.infrastructure.git_service import GitService
from aidycai.services.project_runner import ProjectRunner
from aidycai.services.publisher_service import PublisherService
from aidycai.services.github_actions import GitHubActionsService
from aidycai.services.work_items import WorkItemStore
from aidycai.services.workspace_service import (
    DEFAULT_IGNORED_DIRS,
    is_probably_text,
    read_text_file,
    visible_children,
    write_text_file,
)


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def bundle_summary(bundle: ContextBundle) -> str:
    stats = bundle.statistics
    lines = [
        f"Proyecto: {bundle.project_name}",
        f"Pregunta: {bundle.task}",
        "",
        f"Candidatos: {stats.candidate_files} archivos, {stats.candidate_symbols} símbolos",
        f"Seleccionados: {stats.selected_files} archivos, {stats.selected_lines} líneas",
        f"Contexto: {stats.selected_chars:,} caracteres (~{stats.estimated_tokens:,} tokens)",
        f"Reducción: {stats.reduction_ratio * 100:.1f}%",
        "",
        "PRIMARY",
    ]
    for item in bundle.files:
        if item.role == ROLE_PRIMARY:
            lines.append(f"  {item.path}  · score {item.score:.2f}")
            lines.append(f"    {'; '.join(item.reasons)}")
            for fragment in item.fragments:
                lines.append(
                    f"    L{fragment.line_start}-{fragment.line_end}"
                    + (" · comprimido" if fragment.compressed else "")
                )
    lines.append("")
    lines.append("SECONDARY / REFERENCE")
    for item in bundle.files:
        if item.role != ROLE_PRIMARY:
            lines.append(f"  {item.path} [{item.role}] · score {item.score:.2f}")
            lines.append(f"    {'; '.join(item.reasons)}")
    return "\n".join(lines)


@dataclass
class Conversation:
    id: int
    title: str
    project_id: str | None = None
    query: str = ""
    bundle: ContextBundle | None = None
    search_results: list = field(default_factory=list)
    turns: list[tuple[str, str]] = field(default_factory=list)


class AIDYCAIWindow:
    """Thin GUI layer over the existing application services."""

    def __init__(self, ctk) -> None:
        self.ctk = ctk
        self.root = ctk.CTk()
        self.root.title("AIDYCAI — Local Development Intelligence")
        self.root.geometry("1280x820")
        self.root.minsize(1000, 650)

        self.projects = []
        self.selected_project = None
        self.current_bundle: ContextBundle | None = None
        self.busy = False
        self._operation_id = 0
        self._active_operation_id: int | None = None
        self._background_events: queue.Queue[tuple] = queue.Queue()
        self.conversations: list[Conversation] = []
        self.active_conversation: Conversation | None = None
        self._next_conversation_id = 1
        self._project_runners: dict[str, ProjectRunner] = {}
        self.work_items = WorkItemStore()

        self._build_ui()
        self.new_conversation()
        self.root.after(50, self._poll_background_events)
        self.refresh_projects()

    def _build_ui(self) -> None:
        ctk = self.ctk
        self.root.configure(fg_color=("#F4F7FB", "#0B1120"))
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self.root, width=300, corner_radius=0, fg_color=("#0F172A", "#0F172A"))
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        title = ctk.CTkLabel(
            self.sidebar,
            text="AIDYCAI",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.pack(anchor="w", padx=20, pady=(22, 2))
        ctk.CTkLabel(
            self.sidebar,
            text="Inteligencia local para desarrollo",
            text_color=("#CBD5E1", "#CBD5E1"),
        ).pack(anchor="w", padx=20, pady=(0, 22))

        ctk.CTkLabel(
            self.sidebar, text="CONVERSACIONES", anchor="w",
            text_color="#94A3B8",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(fill="x", padx=20, pady=(0, 8))

        self.new_chat_button = ctk.CTkButton(
            self.sidebar, text="+ Nueva conversación", height=36,
            fg_color="#2563EB", hover_color="#1D4ED8", text_color="#FFFFFF",
            command=self.new_conversation,
        )
        self.new_chat_button.pack(fill="x", padx=18, pady=(0, 10))

        self.conversation_box = ctk.CTkScrollableFrame(
            self.sidebar, height=170, fg_color="#111C31",
        )
        self.conversation_box.pack(fill="x", padx=10, pady=(0, 14))

        ctk.CTkLabel(
            self.sidebar, text="PROYECTOS", anchor="w",
            text_color="#94A3B8",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(fill="x", padx=20, pady=(0, 8))

        self.project_box = ctk.CTkScrollableFrame(self.sidebar, fg_color="#111C31")
        self.project_box.pack(fill="both", expand=True, padx=10)

        ctk.CTkLabel(self.sidebar, text="CENTRO DE TRABAJO", anchor="w",
                     text_color="#94A3B8", font=ctk.CTkFont(size=12, weight="bold")).pack(fill="x", padx=20, pady=(12, 8))
        module_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        module_row.pack(fill="x", padx=12, pady=(0, 10))
        for i, (label, tab) in enumerate((("Tareas", "Tareas"), ("Órdenes", "Órdenes"), ("Incidencias", "Incidencias"))):
            module_row.grid_columnconfigure(i, weight=1)
            ctk.CTkButton(module_row, text=label, height=32,
                          fg_color="#1E293B", hover_color="#334155",
                          command=lambda t=tab: self._show_section(t)).grid(row=0, column=i, padx=2, sticky="ew")

        project_actions = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        project_actions.pack(fill="x", padx=18, pady=(8, 8))
        project_actions.grid_columnconfigure(0, weight=1)
        project_actions.grid_columnconfigure(1, weight=1)
        self.add_project_button = ctk.CTkButton(
            project_actions, text="Agregar…", height=36,
            fg_color="#1E293B", hover_color="#334155", text_color="#F8FAFC",
            command=self.add_project_folder,
        )
        self.add_project_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.discover_button = ctk.CTkButton(
            project_actions, text="Descubrir…", height=36,
            fg_color="#1E293B", hover_color="#334155", text_color="#F8FAFC",
            command=self.discover_projects_folder,
        )
        self.discover_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.refresh_button = ctk.CTkButton(
            self.sidebar, text="Actualizar proyectos", height=36,
            fg_color="#1E293B", hover_color="#334155", text_color="#F8FAFC",
            command=self.refresh_projects,
        )
        self.refresh_button.pack(fill="x", padx=18, pady=(0, 18))

        self.main = ctk.CTkFrame(self.root, corner_radius=0, fg_color=("#F4F7FB", "#0B1120"))
        self.main.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self.main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 8))
        header.grid_columnconfigure(0, weight=1)

        self.project_label = ctk.CTkLabel(
            header, text="Selecciona un proyecto",
            font=ctk.CTkFont(size=22, weight="bold"), anchor="w",
        )
        self.project_label.grid(row=0, column=0, sticky="w")

        self.status_label = ctk.CTkLabel(
            header, text="Listo", anchor="e",
            text_color=("#475569", "#CBD5E1"),
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        query_frame = ctk.CTkFrame(self.main, fg_color=("#FFFFFF", "#172033"), border_width=1, border_color=("#CBD5E1", "#334155"))
        query_frame.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 14))
        query_frame.grid_columnconfigure(0, weight=1)

        self.query = ctk.CTkEntry(
            query_frame,
            placeholder_text="Pregunta sobre el proyecto...",
            height=42, fg_color=("#FFFFFF", "#0F172A"), border_color=("#94A3B8", "#475569"),
            text_color=("#0F172A", "#F8FAFC"), placeholder_text_color=("#64748B", "#94A3B8"),
        )
        self.query.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        self.query.bind("<Return>", lambda _event: self.ask())

        self.ask_button = ctk.CTkButton(
            query_frame, text="Consultar", width=120, height=42, command=self.ask,
            fg_color="#2563EB", hover_color="#1D4ED8", text_color="#FFFFFF",
        )
        self.ask_button.grid(row=0, column=1, padx=(0, 6), pady=12)

        self.search_button = ctk.CTkButton(
            query_frame, text="Buscar", width=100, height=42, command=self.search,
            fg_color=("#E2E8F0", "#334155"), hover_color=("#CBD5E1", "#475569"),
            text_color=("#0F172A", "#F8FAFC"),
        )
        self.search_button.grid(row=0, column=2, padx=(0, 12), pady=12)

        self.result_tabs = ctk.CTkTabview(self.main)
        self.result_tabs.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 12))
        self.result_tabs.add("Conversación")
        self.result_tabs.add("Contexto")
        self.result_tabs.add("Búsqueda")
        self.result_tabs.add("Detalles")
        self.result_tabs.add("Diagnóstico")
        self.result_tabs.add("IDE")
        self.result_tabs.add("Navegador")
        self.result_tabs.add("Tareas")
        self.result_tabs.add("Órdenes")
        self.result_tabs.add("Incidencias")

        self._build_work_items_tabs()
        self._build_ide_tab()
        self._build_browser_tab()

        conversation_tab = self.result_tabs.tab("Conversación")
        conversation_tab.grid_columnconfigure(0, weight=1)
        conversation_tab.grid_rowconfigure(0, weight=1)
        conversation_tab.grid_rowconfigure(1, weight=0)
        conversation_tab.grid_rowconfigure(2, weight=0)

        self.chat_scroll = ctk.CTkScrollableFrame(
            conversation_tab, fg_color=("#F8FAFC", "#0F172A"),
        )
        self.chat_scroll.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))

        self.diagnostic_toggle = ctk.CTkButton(
            conversation_tab,
            text="▸  Mostrar diagnóstico técnico",
            height=30,
            anchor="w",
            fg_color="transparent",
            hover_color=("#E2E8F0", "#1E293B"),
            text_color=("#64748B", "#94A3B8"),
            command=self._toggle_diagnosis,
        )
        self.diagnostic_toggle.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))

        self.diagnostic_panel = ctk.CTkFrame(
            conversation_tab, fg_color=("#F1F5F9", "#111827"),
        )
        self.diagnostic_text = ctk.CTkTextbox(
            self.diagnostic_panel, wrap="word", height=190,
            fg_color=("#F1F5F9", "#111827"), text_color=("#334155", "#CBD5E1"),
        )
        self.diagnosis_text = self.diagnostic_text
        self.diagnostic_text.pack(fill="both", expand=True, padx=8, pady=8)
        self._diagnosis_expanded = False

        self.context_text = ctk.CTkTextbox(
            self.result_tabs.tab("Contexto"), wrap="none",
            fg_color=("#FFFFFF", "#111827"), text_color=("#0F172A", "#F8FAFC"),
        )
        self.context_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.search_text = ctk.CTkTextbox(
            self.result_tabs.tab("Búsqueda"), wrap="none",
            fg_color=("#FFFFFF", "#111827"), text_color=("#0F172A", "#F8FAFC"),
        )
        self.search_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.detail_text = ctk.CTkTextbox(
            self.result_tabs.tab("Detalles"), wrap="none",
            fg_color=("#FFFFFF", "#111827"), text_color=("#0F172A", "#F8FAFC"),
        )
        self.detail_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.diagnosis_tab_text = ctk.CTkTextbox(
            self.result_tabs.tab("Diagnóstico"), wrap="word",
            fg_color=("#FFFFFF", "#111827"), text_color=("#0F172A", "#F8FAFC"),
        )
        self.diagnosis_tab_text.pack(fill="both", expand=True, padx=8, pady=8)

        # Acciones del proyecto en una fila exclusiva. No compartir esta fila
        # con las acciones generales: ambas capas en row=3 ocultaban los botones
        # dinámicos de Ejecutar/Publicar/Deploy/Release.
        self.project_actions_frame = ctk.CTkFrame(
            self.main, fg_color=("#FFFFFF", "#111827"), corner_radius=10,
            border_width=1, border_color=("#E2E8F0", "#24324A")
        )
        self.project_actions_frame.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 8))

        # Acciones generales en una fila independiente.
        actions = ctk.CTkFrame(self.main, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 10))
        for i in range(5):
            actions.grid_columnconfigure(i, weight=1)

        ctk.CTkButton(actions, text="Indexar", command=self.index_project, fg_color=("#E2E8F0", "#334155"), hover_color=("#CBD5E1", "#475569"), text_color=("#0F172A", "#F8FAFC")).grid(
            row=0, column=0, padx=(0, 6), sticky="ew"
        )
        ctk.CTkButton(actions, text="Ver contexto", command=self.show_context, fg_color=("#E2E8F0", "#334155"), hover_color=("#CBD5E1", "#475569"), text_color=("#0F172A", "#F8FAFC")).grid(
            row=0, column=1, padx=6, sticky="ew"
        )
        ctk.CTkButton(actions, text="Exportar JSON", command=lambda: self.export("json"), fg_color=("#E2E8F0", "#334155"), hover_color=("#CBD5E1", "#475569"), text_color=("#0F172A", "#F8FAFC")).grid(
            row=0, column=2, padx=6, sticky="ew"
        )
        ctk.CTkButton(actions, text="Exportar TXT", command=lambda: self.export("txt"), fg_color=("#E2E8F0", "#334155"), hover_color=("#CBD5E1", "#475569"), text_color=("#0F172A", "#F8FAFC")).grid(
            row=0, column=3, padx=6, sticky="ew"
        )
        ctk.CTkButton(actions, text="Abrir archivo", command=self.open_file, fg_color=("#E2E8F0", "#334155"), hover_color=("#CBD5E1", "#475569"), text_color=("#0F172A", "#F8FAFC")).grid(
            row=0, column=4, padx=(6, 0), sticky="ew"
        )

        progress_frame = ctk.CTkFrame(self.main, fg_color="transparent")
        progress_frame.grid(row=5, column=0, sticky="ew", padx=28, pady=(0, 8))
        progress_frame.grid_columnconfigure(0, weight=1)
        self.progress_label = ctk.CTkLabel(
            progress_frame, text="Listo", anchor="w",
            text_color=("#475569", "#CBD5E1"),
        )
        self.progress_label.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.progress_bar = ctk.CTkProgressBar(progress_frame, height=8)
        self.progress_bar.grid(row=1, column=0, sticky="ew")
        self.progress_bar.set(0)

        self.log = ctk.CTkTextbox(self.main, height=105, wrap="word", fg_color=("#E2E8F0", "#111827"), text_color=("#0F172A", "#E2E8F0"))
        self.log.grid(row=6, column=0, sticky="ew", padx=28, pady=(0, 18))
        self.log.configure(state="disabled")

    def _show_section(self, tab_name: str) -> None:
        if hasattr(self, "result_tabs"):
            self.result_tabs.set(tab_name)

    def _build_work_items_tabs(self) -> None:
        for kind, tab_name in (("Tarea", "Tareas"), ("Orden", "Órdenes"), ("Incidencia", "Incidencias")):
            tab = self.result_tabs.tab(tab_name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(1, weight=1)
            header = self.ctk.CTkFrame(tab, fg_color="transparent")
            header.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
            header.grid_columnconfigure(0, weight=1)
            self.ctk.CTkLabel(header, text=tab_name, anchor="w", font=self.ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, sticky="w")
            self.ctk.CTkButton(header, text=f"+ Nueva {kind.lower()}", width=150, height=36,
                               command=lambda k=kind: self._new_work_item(k)).grid(row=0, column=1)
            box = self.ctk.CTkScrollableFrame(tab, fg_color=("#F8FAFC", "#0F172A"))
            box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
            setattr(self, f"{kind.lower()}_box", box)
        self._refresh_work_items()

    def _refresh_work_items(self) -> None:
        for kind in ("Tarea", "Orden", "Incidencia"):
            box = getattr(self, f"{kind.lower()}_box", None)
            if box is None:
                continue
            for widget in box.winfo_children():
                widget.destroy()
            items = [x for x in self.work_items.load() if x.kind == kind]
            if not items:
                self.ctk.CTkLabel(box, text=f"No hay {kind.lower()}s todavía.", text_color=("#64748B", "#94A3B8")).pack(anchor="w", padx=16, pady=20)
                continue
            for item in reversed(items):
                card = self.ctk.CTkFrame(box, fg_color=("#FFFFFF", "#172033"), corner_radius=10,
                                         border_width=1, border_color=("#E2E8F0", "#334155"))
                card.pack(fill="x", padx=8, pady=6)
                left = self.ctk.CTkFrame(card, fg_color="transparent")
                left.pack(side="left", fill="x", expand=True, padx=14, pady=10)
                self.ctk.CTkLabel(left, text=f"#{item.id}  {item.title}", anchor="w",
                                  font=self.ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
                meta = " · ".join(x for x in (item.project, item.priority, item.status) if x)
                self.ctk.CTkLabel(left, text=meta, anchor="w", text_color=("#64748B", "#94A3B8")).pack(anchor="w", pady=(3, 0))
                if item.description:
                    self.ctk.CTkLabel(left, text=item.description, anchor="w", justify="left", wraplength=600).pack(anchor="w", pady=(4, 0))
                self.ctk.CTkButton(card, text="✓", width=38, command=lambda i=item.id: self._complete_work_item(i)).pack(side="right", padx=(4, 12), pady=12)
                self.ctk.CTkButton(card, text="×", width=38, fg_color=("#F1F5F9", "#334155"), text_color=("#0F172A", "#F8FAFC"),
                                   command=lambda i=item.id: self._delete_work_item(i)).pack(side="right", padx=4, pady=12)

    def _new_work_item(self, kind: str) -> None:
        win = self.ctk.CTkToplevel(self.root)
        win.title(f"Nueva {kind.lower()}")
        win.geometry("520x430")
        win.transient(self.root)
        win.grab_set()
        frame = self.ctk.CTkFrame(win, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=24, pady=24)
        self.ctk.CTkLabel(frame, text=f"Nueva {kind.lower()}", font=self.ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(0, 16))
        title = self.ctk.CTkEntry(frame, placeholder_text="Título")
        title.pack(fill="x", pady=6)
        project = self.ctk.CTkEntry(frame, placeholder_text="Proyecto (opcional)")
        project.pack(fill="x", pady=6)
        priority = self.ctk.CTkComboBox(frame, values=["Baja", "Media", "Alta", "Crítica"])
        priority.set("Media")
        priority.pack(fill="x", pady=6)
        desc = self.ctk.CTkTextbox(frame, height=130, wrap="word")
        desc.pack(fill="both", expand=True, pady=6)
        def save() -> None:
            if not title.get().strip():
                messagebox.showwarning("AIDYCAI", "Escribe un título.", parent=win)
                return
            self.work_items.create(kind, title.get(), desc.get("1.0", "end").strip(), project.get(), priority.get())
            self._refresh_work_items()
            win.destroy()
        self.ctk.CTkButton(frame, text="Crear", height=38, command=save).pack(fill="x", pady=(10, 0))

    def _complete_work_item(self, item_id: int) -> None:
        self.work_items.update_status(item_id, "Completada")
        self._refresh_work_items()

    def _delete_work_item(self, item_id: int) -> None:
        self.work_items.delete(item_id)
        self._refresh_work_items()

    def _build_ide_tab(self) -> None:
        """Build a lightweight local IDE using Tk/CustomTkinter primitives.

        It deliberately edits files in-place inside the selected project only; it
        does not copy, index, or modify external projects unless the user saves.
        """
        tab = self.result_tabs.tab("IDE")
        tab.grid_columnconfigure(0, weight=0, minsize=280)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        toolbar = self.ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        self.ide_path_label = self.ctk.CTkLabel(toolbar, text="Ningún archivo seleccionado", anchor="w")
        self.ide_path_label.pack(side="left", fill="x", expand=True)
        self.ide_save_button = self.ctk.CTkButton(toolbar, text="Guardar", width=90, command=self._save_editor_file)
        self.ide_save_button.pack(side="right", padx=4)
        self.ide_reload_button = self.ctk.CTkButton(toolbar, text="Recargar", width=90, command=self._reload_editor_file)
        self.ide_reload_button.pack(side="right", padx=4)
        self.ide_open_button = self.ctk.CTkButton(toolbar, text="Abrir externo", width=105, command=self._open_editor_external)
        self.ide_open_button.pack(side="right", padx=4)

        tree_frame = self.ctk.CTkFrame(tab, fg_color=("#FFFFFF", "#111827"))
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(4, 8))
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.file_tree = ttk.Treeview(tree_frame, show="tree")
        self.file_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.file_tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.file_tree.configure(yscrollcommand=tree_scroll.set)
        self.file_tree.bind("<<TreeviewOpen>>", self._expand_tree_node)
        self.file_tree.bind("<Double-1>", self._open_tree_file)

        editor_frame = self.ctk.CTkFrame(tab, fg_color=("#FFFFFF", "#111827"))
        editor_frame.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(4, 8))
        editor_frame.grid_rowconfigure(0, weight=1)
        editor_frame.grid_columnconfigure(0, weight=1)
        self.editor = self.ctk.CTkTextbox(editor_frame, wrap="none", undo=True,
                                          fg_color=("#FFFFFF", "#0B1120"),
                                          text_color=("#0F172A", "#F8FAFC"),
                                          font=("Consolas", 12))
        self.editor.grid(row=0, column=0, sticky="nsew")
        editor_y = ttk.Scrollbar(editor_frame, orient="vertical", command=self.editor.yview)
        editor_y.grid(row=0, column=1, sticky="ns")
        self.editor.configure(yscrollcommand=editor_y.set)
        self._editor_file: Path | None = None

    def _build_browser_tab(self) -> None:
        """Provide a browser control center without embedding a second browser engine.

        ChatGPT/Kimi and modern web apps require a full browser engine, so AIDYCAI
        launches the user's default browser rather than pretending to be a browser.
        """
        tab = self.result_tabs.tab("Navegador")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        row = self.ctk.CTkFrame(tab, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        row.grid_columnconfigure(0, weight=1)
        self.browser_url = self.ctk.CTkEntry(row, height=40, placeholder_text="https://...")
        self.browser_url.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.ctk.CTkButton(row, text="Abrir", width=90, command=self._open_browser_url).grid(row=0, column=1)

        presets = self.ctk.CTkFrame(tab, fg_color="transparent")
        presets.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        for col in range(5):
            presets.grid_columnconfigure(col, weight=1)
        links = [
            ("ChatGPT", "https://chatgpt.com"),
            ("Kimi", "https://www.kimi.com"),
            ("GitHub", "https://github.com"),
            ("PythonAnywhere", "https://www.pythonanywhere.com"),
            ("Proyecto", None),
        ]
        for col, (label, url) in enumerate(links):
            command = self._open_selected_project_url if url is None else lambda u=url: self._open_web_url(u)
            self.ctk.CTkButton(presets, text=label, command=command).grid(row=0, column=col, padx=3, sticky="ew")

        self.browser_info = self.ctk.CTkLabel(
            tab,
            text="Navegador externo: AIDYCAI conserva el workspace y abre el navegador completo del sistema para sitios modernos.",
            anchor="nw", justify="left",
        )
        self.browser_info.grid(row=2, column=0, sticky="nw", padx=14, pady=14)

    def _populate_file_tree(self, project) -> None:
        if not hasattr(self, "file_tree"):
            return
        self.file_tree.delete(*self.file_tree.get_children())
        root_path = project.path
        if not root_path.is_dir():
            return
        root_id = self.file_tree.insert("", "end", text=root_path.name, values=(str(root_path),), open=True)
        self._insert_tree_children(root_id, root_path)

    def _insert_tree_children(self, node_id: str, path: Path) -> None:
        for child in visible_children(path, DEFAULT_IGNORED_DIRS):
            if child.is_dir():
                item = self.file_tree.insert(node_id, "end", text=f"📁 {child.name}", values=(str(child),))
                self.file_tree.insert(item, "end", text="…")
            else:
                self.file_tree.insert(node_id, "end", text=child.name, values=(str(child),))

    def _expand_tree_node(self, _event=None) -> None:
        selection = self.file_tree.selection()
        if not selection:
            return
        node = selection[0]
        values = self.file_tree.item(node, "values")
        if not values:
            return
        path = Path(values[0])
        if not path.is_dir():
            return
        children = self.file_tree.get_children(node)
        if len(children) == 1 and self.file_tree.item(children[0], "text") == "…":
            self.file_tree.delete(children[0])
            self._insert_tree_children(node, path)

    def _open_tree_file(self, _event=None) -> None:
        selection = self.file_tree.selection()
        if not selection:
            return
        values = self.file_tree.item(selection[0], "values")
        if not values:
            return
        path = Path(values[0])
        if path.is_dir():
            return
        if not is_probably_text(path):
            messagebox.showinfo("AIDYCAI", "Este archivo no parece ser de texto. Puedes abrirlo con la aplicación del sistema.", parent=self.root)
            return
        try:
            text = read_text_file(path)
        except Exception as exc:
            messagebox.showerror("AIDYCAI", str(exc), parent=self.root)
            return
        self._editor_file = path
        self.ide_path_label.configure(text=str(path))
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)

    def _save_editor_file(self) -> None:
        if self._editor_file is None:
            return
        try:
            write_text_file(self._editor_file, self.editor.get("1.0", "end-1c"))
            self._log(f"[OK] Archivo guardado: {self._editor_file}")
        except Exception as exc:
            messagebox.showerror("AIDYCAI", f"No se pudo guardar: {exc}", parent=self.root)

    def _reload_editor_file(self) -> None:
        if self._editor_file is None:
            return
        try:
            text = read_text_file(self._editor_file)
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", text)
        except Exception as exc:
            messagebox.showerror("AIDYCAI", str(exc), parent=self.root)

    def _open_editor_external(self) -> None:
        if self._editor_file and self._editor_file.exists():
            os.startfile(str(self._editor_file)) if os.name == "nt" else webbrowser.open(self._editor_file.as_uri())

    def _open_web_url(self, url: str) -> None:
        self.browser_url.delete(0, "end")
        self.browser_url.insert(0, url)
        webbrowser.open(url, new=2)

    def _open_browser_url(self) -> None:
        url = self.browser_url.get().strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._open_web_url(url)

    def _open_selected_project_url(self) -> None:
        if not self.selected_project:
            return
        actions = self._actions_for(self.selected_project)
        if not actions.url:
            messagebox.showinfo("AIDYCAI", "Este proyecto no tiene una URL local configurada.", parent=self.root)
            return
        self._open_web_url(actions.url)

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def refresh_projects(self) -> None:
        def operation():
            with open_app(seed=False) as app:
                return app.registry.list_projects()

        self._run_background(operation, self._set_projects, "Actualizando proyectos")

    def add_project_folder(self) -> None:
        from tkinter import filedialog, simpledialog

        from aidycai.application.project_discovery import default_search_root

        path = filedialog.askdirectory(
            parent=self.root,
            title="Selecciona la carpeta del proyecto",
            initialdir=str(default_search_root()),
        )
        if not path:
            return
        folder = Path(path)
        name = simpledialog.askstring(
            "AIDYCAI",
            "Nombre del proyecto:",
            initialvalue=folder.name,
            parent=self.root,
        )
        if not name or not name.strip():
            return

        def operation():
            with open_app(seed=False) as app:
                project = app.registry.add(name.strip(), folder)
                app.ensure_project_data(project.id)
                return app.registry.list_projects(), project.name

        def on_done(result) -> None:
            projects, project_name = result
            self._set_projects(projects)
            self._set_status(f"Registrado {project_name}")
            self._log(f"Proyecto agregado: {project_name} -> {folder}")

        self._run_background(operation, on_done, f"Registrando {name.strip()}")

    def discover_projects_folder(self) -> None:
        from tkinter import filedialog

        from aidycai.application.project_discovery import default_search_root, discover_projects
        from aidycai.domain.exceptions import DuplicateProjectError, InvalidPathError

        root = filedialog.askdirectory(
            parent=self.root,
            title="Carpeta donde buscar proyectos",
            initialdir=str(default_search_root()),
        )
        if not root:
            return

        def operation():
            with open_app(seed=False) as app:
                found = discover_projects(root, depth=1, registered=app.registry.list_projects())
                added_names: list[str] = []
                for item in found:
                    if item.already_registered:
                        continue
                    try:
                        project = app.registry.add(item.name, item.path)
                        app.ensure_project_data(project.id)
                        added_names.append(project.name)
                    except (DuplicateProjectError, InvalidPathError):
                        continue
                return app.registry.list_projects(), found, added_names

        def on_done(result) -> None:
            projects, found, added_names = result
            self._set_projects(projects)
            total = len(found)
            new_count = sum(1 for item in found if not item.already_registered)
            if not found:
                messagebox.showinfo(
                    "AIDYCAI",
                    f"No se encontraron proyectos en:\n{root}",
                    parent=self.root,
                )
                return
            messagebox.showinfo(
                "AIDYCAI",
                (
                    f"Encontrados: {total}\n"
                    f"Nuevos candidatos: {new_count}\n"
                    f"Registrados ahora: {len(added_names)}\n"
                    + (", ".join(added_names) if added_names else "Ninguno nuevo.")
                ),
                parent=self.root,
            )
            self._set_status(f"Descubrimiento: +{len(added_names)}")
            self._log(f"Descubrimiento en {root}: +{len(added_names)} de {total}")

        self._run_background(operation, on_done, "Descubriendo proyectos")

    def _set_projects(self, projects) -> None:
        self.projects = list(projects)
        for widget in self.project_box.winfo_children():
            widget.destroy()

        if not self.projects:
            self.ctk.CTkLabel(self.project_box, text="No hay proyectos registrados.").pack(
                anchor="w", padx=10, pady=10
            )
            return

        for project in self.projects:
            exists = project.path.exists() and project.path.is_dir()
            state = "●" if project.active and exists else "○"
            text = f"{state}  {project.name}"
            button = self.ctk.CTkButton(
                self.project_box,
                text=text,
                anchor="w",
                fg_color="transparent",
                hover_color="#243B63",
                text_color="#F8FAFC",
                command=lambda p=project: self.select_project(p),
            )
            button.pack(fill="x", pady=2)

        if self.selected_project:
            match = next(
                (p for p in self.projects if p.id == self.selected_project.id), None
            )
            if match:
                self.select_project(match)
        elif self.projects:
            self.select_project(self.projects[0])

    def _refresh_conversations(self) -> None:
        for widget in self.conversation_box.winfo_children():
            widget.destroy()
        for conversation in self.conversations:
            active = conversation is self.active_conversation
            button = self.ctk.CTkButton(
                self.conversation_box,
                text=("●  " if active else "   ") + conversation.title,
                anchor="w", height=34,
                fg_color=("#1D4ED8", "#1D4ED8") if active else "transparent",
                hover_color="#243B63", text_color="#F8FAFC",
                command=lambda c=conversation: self.select_conversation(c),
            )
            button.pack(fill="x", pady=2)

    def new_conversation(self) -> None:
        conversation = Conversation(id=self._next_conversation_id, title=f"Conversación {self._next_conversation_id}")
        self._next_conversation_id += 1
        self.conversations.append(conversation)
        self.active_conversation = conversation
        self.current_bundle = None
        self._refresh_conversations()
        self._restore_conversation()
        if hasattr(self, "result_tabs"):
            self.result_tabs.set("Conversación")

    def select_conversation(self, conversation: Conversation) -> None:
        self.active_conversation = conversation
        if conversation.project_id:
            project = next((item for item in self.projects if item.id == conversation.project_id), None)
            if project is not None:
                self.selected_project = project
        self.current_bundle = conversation.bundle
        self._refresh_conversations()
        self._restore_conversation()

    def _restore_conversation(self) -> None:
        conversation = self.active_conversation
        if conversation is None:
            return
        self.query.delete(0, "end")
        if conversation.query:
            self.query.insert(0, conversation.query)
        self.context_text.delete("1.0", "end")
        self.detail_text.delete("1.0", "end")
        self.diagnostic_text.delete("1.0", "end")
        self.diagnosis_tab_text.delete("1.0", "end")
        self.search_text.delete("1.0", "end")
        self._render_conversation()
        if conversation.bundle:
            self.context_text.insert("end", conversation.bundle.to_text())
            self.detail_text.insert("end", bundle_summary(conversation.bundle))
            diagnosis = render_diagnosis(conversation.bundle)
            self.diagnostic_text.insert("end", diagnosis)
            self.diagnosis_tab_text.insert("end", diagnosis)
        if conversation.search_results:
            for hit in conversation.search_results:
                lines = str(hit.line_start) if hit.line_start and hit.line_end is None else (f"{hit.line_start}-{hit.line_end}" if hit.line_start else "")
                self.search_text.insert(
                    "end",
                    f"{hit.kind or hit.symbol_type:<12} {hit.rel_path}  {hit.qualified_name or ''}  {lines}  score={hit.score:.3f}\n",
                )
        self.project_label.configure(text=self.selected_project.name if self.selected_project else "Selecciona un proyecto")
        self._set_status("Listo")

    def _render_conversation(self) -> None:
        """Render each turn as a simple two-sided chat: user right, AIDYCAI left."""
        if not hasattr(self, "chat_scroll"):
            return
        for widget in self.chat_scroll.winfo_children():
            widget.destroy()
        conversation = self.active_conversation
        if conversation is None or not conversation.turns:
            self.ctk.CTkLabel(
                self.chat_scroll,
                text="Haz una pregunta sobre el proyecto para comenzar.",
                text_color=("#64748B", "#94A3B8"),
            ).pack(anchor="center", pady=40)
            return

        for prompt, answer in conversation.turns:
            row = self.ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=8)
            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=1)

            ai_bubble = self.ctk.CTkFrame(
                row, fg_color=("#FFFFFF", "#172033"), corner_radius=14,
                border_width=1, border_color=("#E2E8F0", "#334155"),
            )
            ai_bubble.grid(row=0, column=0, sticky="w", padx=(0, 28))
            self.ctk.CTkLabel(
                ai_bubble, text="AIDYCAI", anchor="w",
                font=self.ctk.CTkFont(size=11, weight="bold"),
                text_color=("#2563EB", "#60A5FA"),
            ).pack(anchor="w", padx=14, pady=(10, 2))
            self.ctk.CTkLabel(
                ai_bubble, text=answer, anchor="w", justify="left",
                wraplength=520,
                text_color=("#0F172A", "#F8FAFC"),
            ).pack(anchor="w", padx=14, pady=(0, 12))

            user_bubble = self.ctk.CTkFrame(
                row, fg_color=("#DBEAFE", "#1D4ED8"), corner_radius=14,
            )
            user_bubble.grid(row=0, column=1, sticky="e", padx=(28, 0))
            self.ctk.CTkLabel(
                user_bubble, text="TÚ", anchor="w",
                font=self.ctk.CTkFont(size=11, weight="bold"),
                text_color=("#1E40AF", "#DBEAFE"),
            ).pack(anchor="w", padx=14, pady=(10, 2))
            self.ctk.CTkLabel(
                user_bubble, text=prompt, anchor="w", justify="left",
                wraplength=520,
                text_color=("#0F172A", "#FFFFFF"),
            ).pack(anchor="w", padx=14, pady=(0, 12))

        self.root.after(10, lambda: self.chat_scroll._parent_canvas.yview_moveto(1.0))

    def _toggle_diagnosis(self) -> None:
        self._diagnosis_expanded = not self._diagnosis_expanded
        if self._diagnosis_expanded:
            self.diagnostic_panel.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
            self.diagnostic_toggle.configure(text="▾  Ocultar diagnóstico técnico")
        else:
            self.diagnostic_panel.grid_forget()
            self.diagnostic_toggle.configure(text="▸  Mostrar diagnóstico técnico")

    def _actions_for(self, project) -> ProjectActions:
        spec = get_project_config(project.name)
        if spec is not None:
            return ProjectActions(
                command=spec.command, venv=spec.venv, open_browser=spec.open_browser,
                url=spec.url, browser_delay=spec.browser_delay, branch=spec.branch,
                github_owner=spec.github_owner, github_repo=spec.github_repo, publish=spec.publish,
                deploy=spec.deploy, deploy_user=spec.deploy_user, deploy_host=spec.deploy_host,
                deploy_path=spec.deploy_path, deploy_script=spec.deploy_script,
                build_workflow=spec.build_workflow, build_input_name=spec.build_input_name,
                extra_env=spec.extra_env,
            )
        for fallback in DEFAULT_PROJECTS:
            if fallback.name.lower() == project.name.lower():
                return fallback.actions
        return ProjectActions()

    def _clear_project_action_buttons(self) -> None:
        for widget in self.project_actions_frame.winfo_children():
            widget.destroy()

    def _render_project_actions(self, project) -> None:
        self._clear_project_action_buttons()
        actions = self._actions_for(project)
        self.project_actions_frame.grid_columnconfigure(0, weight=1)
        title = self.ctk.CTkLabel(self.project_actions_frame, text="Acciones del proyecto", anchor="w",
                                  font=self.ctk.CTkFont(size=12, weight="bold"),
                                  text_color=("#475569", "#94A3B8"))
        title.grid(row=0, column=0, sticky="w", padx=14, pady=(8, 2))
        row = self.ctk.CTkFrame(self.project_actions_frame, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 8))
        for col in range(6):
            row.grid_columnconfigure(col, weight=1)
        buttons = []
        if actions.can_execute:
            buttons.extend([("Ejecutar", lambda p=project, a=actions: self._execute_project(p, a)),
                            ("Detener", lambda p=project: self._stop_project(p))])
        buttons.append(("Recargar", lambda p=project, a=actions: self._reload_project(p, a)))
        if actions.can_publish:
            buttons.append(("Publicar", lambda p=project, a=actions: self._publish_project(p, a, False)))
        if actions.can_deploy:
            buttons.append(("Publicar + Deploy", lambda p=project, a=actions: self._publish_project(p, a, True)))
            buttons.append(("Deploy", lambda p=project, a=actions: self._deploy_only(p, a)))
        if actions.can_build:
            buttons.append(("Compilar EXE", lambda p=project, a=actions: self._build_release(p, a)))
        for col, (text, command) in enumerate(buttons):
            self.ctk.CTkButton(row, text=text, height=34, command=command,
                               fg_color=("#F8FAFC", "#1E293B"), hover_color=("#E2E8F0", "#334155"),
                               text_color=("#0F172A", "#F8FAFC")).grid(row=0, column=col, padx=3, sticky="ew")

    def _execute_project(self, project, actions: ProjectActions) -> None:
        runner = self._project_runners.setdefault(project.id, ProjectRunner())
        if runner.is_running():
            self._log(f"[WARN] {project.name} ya está ejecutándose.")
            return
        def output(line: str) -> None:
            self.root.after(0, lambda: self._log(f"[{project.name}] {line}"))
        try:
            runner.start_project(actions.command or "", project.path, venv=actions.venv, on_output=output, env=actions.extra_env, open_browser=actions.open_browser, url=actions.url, browser_delay=actions.browser_delay)
            self._set_status(f"{project.name} ejecutándose")
            self._log(f"[OK] Ejecutando: {actions.command} · Python: {runner.executable}")
        except Exception as exc:
            self._log(f"[ERROR] {exc}")

    def _stop_project(self, project) -> None:
        runner = self._project_runners.get(project.id)
        if not runner:
            self._log(f"[INFO] {project.name} no tiene un proceso activo.")
            return
        try:
            runner.stop_project()
            self._log(f"[OK] Proceso detenido: {project.name}")
            self._set_status("Listo")
        except Exception as exc:
            self._log(f"[ERROR] {exc}")

    def _publish_project(self, project, actions: ProjectActions, deploy: bool) -> None:
        from tkinter import simpledialog, messagebox
        message = simpledialog.askstring("Publicar", f"Mensaje de commit para {project.name}:", parent=self.root)
        if not message:
            return
        def operation():
            return PublisherService(project.path, actions).publish(message, deploy=deploy)
        def success(result):
            self._log(f"[OK] Publicación completada. Commit: {'sí' if result.committed else 'no'} · rama {result.branch} · deploy {'sí' if result.deployed else 'no'}")
            if deploy:
                messagebox.showinfo("AIDYCAI", f"{project.name}: publicación y deploy completados.", parent=self.root)
        self._run_background(operation, success, "Publicando")

    def _deploy_only(self, project, actions: ProjectActions) -> None:
        def operation():
            return PublisherService(project.path, actions).deploy_only()
        def success(output):
            self._log("[OK] Deploy remoto completado.")
            if output:
                self._log(output.strip())
        self._run_background(operation, success, "Desplegando")

    def _reload_project(self, project, actions: ProjectActions) -> None:
        def operation():
            result = GitService(project.path).reload(actions.branch)
            with open_app(seed=False) as app:
                summary = app.index_service().index_project(project.id, rebuild=False, progress=self._index_progress_callback)
            return result, summary
        def success(result):
            _, summary = result
            self._log(f"[OK] Recarga completada y reindexada: {summary.files_found} archivos.")
        self._run_background(operation, success, "Recargando proyecto", refresh_projects=True)

    def _build_release(self, project, actions: ProjectActions) -> None:
        from tkinter import simpledialog, messagebox
        version = simpledialog.askstring("Compilar EXE", "Versión (ej. v25.1):", parent=self.root)
        if not version:
            return
        def operation():
            service = GitHubActionsService(actions.github_owner or "", actions.github_repo or "")
            if not service.workflow_exists(actions.build_workflow or ""):
                raise RuntimeError(f"No se encontró el workflow '{actions.build_workflow}' en GitHub.")
            return service.dispatch(actions.build_workflow or "", actions.branch, {actions.build_input_name: version})
        def success(ok):
            self._log(f"[OK] Workflow {actions.build_workflow} disparado para {version}.")
            messagebox.showinfo("AIDYCAI", f"Compilación iniciada para {version}. Revisa GitHub Actions.", parent=self.root)
        self._run_background(operation, success, "Disparando compilación")

    def select_project(self, project) -> None:
        self.selected_project = project
        if self.active_conversation:
            self.active_conversation.project_id = project.id
        self.project_label.configure(text=project.name)
        self._set_status("Listo")
        self._render_project_actions(project)
        self._populate_file_tree(project)
        if hasattr(self, "browser_url"):
            actions = self._actions_for(project)
            self.browser_url.delete(0, "end")
            if actions.url:
                self.browser_url.insert(0, actions.url)
        self._log(f"[INFO] Proyecto seleccionado: {project.name}")

    def _require_project(self):
        if self.selected_project is None:
            self._log("[WARN] Selecciona un proyecto primero.")
            return None
        return self.selected_project

    def _run_background(
        self,
        operation: Callable,
        success: Callable,
        label: str,
        progress: Callable[[str, int, int, str | None], None] | None = None,
        *,
        refresh_projects: bool = False,
    ) -> None:
        if self.busy:
            self._log("[WARN] Ya hay una operación en curso.")
            return

        self._operation_id += 1
        operation_id = self._operation_id
        self._active_operation_id = operation_id
        self.busy = True
        self._set_status(label + "...")
        self._set_progress(label, 0, 0, None)
        self._log("[INFO] " + label + "...")

        def worker() -> None:
            try:
                result = operation()
                self._background_events.put(("complete", operation_id, success, result, refresh_projects))
            except Exception as exc:
                self._background_events.put(("error", operation_id, exc, refresh_projects))

        threading.Thread(target=worker, daemon=True, name=f"aidycai-{operation_id}").start()

    def _poll_background_events(self) -> None:
        try:
            while True:
                event = self._background_events.get_nowait()
                kind, operation_id, *payload = event
                if operation_id != self._active_operation_id:
                    continue

                if kind == "progress":
                    stage, done, total, current = payload
                    self._set_progress(stage, done, total, current)
                    continue

                if kind == "log":
                    self._log(payload[0])
                    continue

                if kind == "complete":
                    success, result, refresh_projects = payload
                    try:
                        success(result)
                    except Exception as exc:
                        self._set_operation_error(exc)
                    finally:
                        self._finish_operation(operation_id)
                    if refresh_projects:
                        self.refresh_projects()
                    continue

                if kind == "error":
                    exc, refresh_projects = payload
                    try:
                        self._error(exc)
                    finally:
                        self._finish_operation(operation_id)
                    if refresh_projects:
                        self.refresh_projects()
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._poll_background_events)

    def _finish_operation(self, operation_id: int | None = None) -> None:
        if operation_id is not None and operation_id != self._active_operation_id:
            return
        # Clear the logical lock before touching widgets so a UI exception
        # cannot leave the application permanently busy.
        self.busy = False
        self._active_operation_id = None
        try:
            self._set_status("Listo")
        except Exception:
            traceback.print_exc()

    def _set_progress(self, stage: str, done: int, total: int, current: str | None) -> None:
        if total > 0:
            value = min(1.0, max(0.0, done / total))
            self.progress_bar.set(value)
            suffix = f" · {done:,}/{total:,}"
        else:
            self.progress_bar.set(0)
            suffix = ""
        labels = {
            "scan": "Escaneando archivos",
            "prepare": "Preparando archivos nuevos",
            "analyze": "Analizando archivos",
            "graph": "Actualizando grafo de imports",
            "done": "Indexación completada",
        }
        text = labels.get(stage, stage) + suffix
        if current:
            text += f" · {current}"
        self.progress_label.configure(text=text)
        self.status_label.configure(text=text)

    def _index_progress_callback(self, stage: str, done: int, total: int, current: str | None) -> None:
        operation_id = self._active_operation_id
        if operation_id is not None:
            self._background_events.put(("progress", operation_id, stage, done, total, current))

    def _worker_log(self, message: str) -> None:
        operation_id = self._active_operation_id
        if operation_id is not None:
            self._background_events.put(("log", operation_id, message))

    def _set_operation_error(self, exc: Exception) -> None:
        self._set_status("Error")
        self.progress_label.configure(text="Operación detenida por un error")
        self.progress_bar.set(0)
        self._log(f"[ERROR] {exc}")

    def ask(self) -> None:
        project = self._require_project()
        task = self.query.get().strip()
        if not project or not task:
            self._log("[WARN] Escribe una pregunta.")
            return

        conversation = self.active_conversation

        def operation():
            with open_app(seed=False) as app:
                index_service = app.index_service()
                stats = index_service.stats(project.id)
                if stats.last_indexed_at is None:
                    self._index_progress_callback("scan", 0, 0, "Índice no encontrado · indexando automáticamente")
                    self._worker_log("[INFO] No hay índice para el proyecto; indexando automáticamente...")
                    index_service.index_project(project.id, progress=self._index_progress_callback)
                    self._worker_log("[OK] Índice creado. Continuando con la construcción de contexto...")
                return app.context_engine().build(project.id, task)

        def success(bundle):
            conversation.bundle = bundle
            conversation.query = task
            conversation.project_id = project.id
            conversation.title = task[:42] + ("…" if len(task) > 42 else "")
            answer = render_human_answer(bundle)
            conversation.turns.append((task, answer))
            self._refresh_conversations()
            if self.active_conversation is conversation:
                self.current_bundle = bundle
            self.context_text.delete("1.0", "end")
            self.context_text.insert("end", bundle.to_text())
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("end", bundle_summary(bundle))
            diagnosis = render_diagnosis(bundle)
            self.diagnostic_text.delete("1.0", "end")
            self.diagnostic_text.insert("end", diagnosis)
            self.diagnosis_tab_text.delete("1.0", "end")
            self.diagnosis_tab_text.insert("end", diagnosis)
            self._restore_conversation()
            self.result_tabs.set("Conversación")
            self._log(
                f"[OK] ContextBundle: {bundle.statistics.selected_files} archivos, "
                f"{bundle.statistics.selected_lines} líneas."
            )

        self._run_background(operation, success, "Construyendo contexto")

    def show_context(self) -> None:
        if self.current_bundle is None:
            self._log("[WARN] Todavía no hay un ContextBundle.")
            return
        self.context_text.delete("1.0", "end")
        self.context_text.insert("end", self.current_bundle.to_text())
        self.result_tabs.set("Contexto")

    def search(self) -> None:
        project = self._require_project()
        query = self.query.get().strip()
        if not project or not query:
            self._log("[WARN] Escribe algo para buscar.")
            return

        conversation = self.active_conversation

        def operation():
            with open_app(seed=False) as app:
                return app.index_service().search(project.id, query, limit=50)

        def success(hits):
            conversation.search_results = list(hits)
            conversation.query = query
            self.search_text.delete("1.0", "end")
            if not hits:
                self.search_text.insert("end", "Sin resultados.\n")
            else:
                for hit in hits:
                    lines = ""
                    if hit.line_start:
                        lines = str(hit.line_start) if hit.line_end is None else f"{hit.line_start}-{hit.line_end}"
                    self.search_text.insert(
                        "end",
                        f"{hit.kind or hit.symbol_type:<12} {hit.rel_path}"
                        f"  {hit.qualified_name or ''}  {lines}  score={hit.score:.3f}\n"
                    )
            self.result_tabs.set("Búsqueda")
            self._log(f"[OK] Búsqueda completada: {len(hits)} resultados.")

        self._run_background(operation, success, "Buscando")

    def index_project(self) -> None:
        project = self._require_project()
        if not project:
            return

        def operation():
            with open_app(seed=False) as app:
                return app.index_service().index_project(
                    project.id, rebuild=True, progress=self._index_progress_callback
                )

        def success(summary):
            self._set_progress("done", summary.files_found, summary.files_found, None)
            self._log(
                f"[OK] Índice actualizado: {summary.files_found:,} archivos; "
                f"{summary.files_created + summary.files_modified} creados/modificados; "
                f"{summary.symbols:,} símbolos; {summary.imports:,} imports; "
                f"{summary.errors} errores; {summary.duration_s:.1f}s."
            )

        self._run_background(operation, success, "Indexando proyecto", refresh_projects=True)

    def export(self, kind: str) -> None:
        if self.current_bundle is None:
            self._log("[WARN] Genera primero un contexto.")
            return
        from tkinter import filedialog

        ext = ".json" if kind == "json" else ".txt"
        path = filedialog.asksaveasfilename(
            title="Exportar ContextBundle",
            defaultextension=ext,
            filetypes=[("JSON" if kind == "json" else "Texto", "*" + ext)],
        )
        if not path:
            return
        content = self.current_bundle.to_json() if kind == "json" else self.current_bundle.to_text()
        Path(path).write_text(content, encoding="utf-8")
        self._log(f"[OK] Exportado: {path}")

    def open_file(self) -> None:
        if self.current_bundle is None or self.selected_project is None:
            self._log("[WARN] Genera un contexto primero.")
            return

        candidates = [item for item in self.current_bundle.files]
        if not candidates:
            self._log("[WARN] El contexto no contiene archivos.")
            return

        # Open the first selected file; future versions can expose a file picker.
        rel = candidates[0].path
        path = (self.selected_project.path / rel).resolve()
        try:
            path.relative_to(self.selected_project.path.resolve())
        except ValueError:
            self._log("[ERROR] Ruta fuera del proyecto bloqueada.")
            return

        if not path.exists():
            self._log(f"[ERROR] No existe: {path}")
            return

        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
        self._log(f"[INFO] Abriendo: {path}")

    def _error(self, exc: Exception) -> None:
        self._set_status("Error")
        self.progress_label.configure(text=f"Error: {type(exc).__name__}")
        self.progress_bar.set(0)
        message = f"{type(exc).__name__}: {exc}"
        self._log("[ERROR] " + message)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        try:
            from tkinter import messagebox
            messagebox.showerror("AIDYCAI — Operación fallida", message, parent=self.root)
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()


def run_gui() -> None:
    try:
        import customtkinter as ctk
    except ImportError as exc:
        raise RuntimeError(
            "La GUI requiere CustomTkinter. Ejecuta: pip install -e '.[gui]'"
        ) from exc

    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    AIDYCAIWindow(ctk).run()
