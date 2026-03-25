from tkinter import messagebox, ttk, filedialog
from tkinter import font as tkfont
import tkinter as tk
import threading
import time
import random
import re
import json
from pathlib import Path
import os
import sys
import tempfile
from datetime import datetime
try:
    import serial
except ImportError:
    serial = None

PORTA_DEFAULT = "COM12"
BAUD = 9600
USE_SERIAL = True
NUM_MAX_ATLETI = 12
INTERDISCIPLINARY_SUBJECT = "INTERDISCIPLINARE"


def _normalize_qa_entry(entry, subject_name: str, level: str):
    if isinstance(entry, str):
        question = entry.strip()
        if question:
            return {"question": question, "answer": "", "subject": subject_name, "level": level}
        return None
    if isinstance(entry, dict):
        q = str(entry.get("question", "")).strip()
        a = str(entry.get("answer", "")).strip()
        if q:
            return {"question": q, "answer": a, "subject": subject_name, "level": level}
    return None


LEVELS = ("Facile", "Media", "Difficile", "Plus")


def get_base_dir() -> Path:
    # PyInstaller extracts bundled data under _MEIPASS at runtime.
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


QUESTIONS_DIR = get_base_dir() / "questions"


def load_question_subjects():
    subjects = {}
    if not QUESTIONS_DIR.exists():
        return subjects

    for path in sorted(QUESTIONS_DIR.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                raw = json.load(f)
        except Exception:
            continue

        if not isinstance(raw, dict):
            continue

        levels_raw = raw.get("levels", raw)
        if not isinstance(levels_raw, dict):
            continue

        subject_name = str(raw.get("subject", path.stem)).strip() or path.stem
        bank = {}
        for level in LEVELS:
            entries = levels_raw.get(level, [])
            if not isinstance(entries, list):
                entries = []
            normalized = []
            for entry in entries:
                item = _normalize_qa_entry(entry, subject_name, level)
                if item:
                    normalized.append(item)
            bank[level] = normalized

        if not all(bank[level] for level in LEVELS):
            continue

        subjects[subject_name] = bank

    interdisciplinary_subjects = {
        name: {level: [item.copy() for item in bank[level]] for level in LEVELS}
        for name, bank in subjects.items()
    }
    if interdisciplinary_subjects:
        subjects[INTERDISCIPLINARY_SUBJECT] = {
            "__interdisciplinary__": True,
            "subjects": interdisciplinary_subjects
        }

    return subjects

def format_time(seconds: float) -> str:
    total_centiseconds = int(seconds * 100)
    minutes = total_centiseconds // 6000
    secs = (total_centiseconds // 100) % 60
    centis = total_centiseconds % 100
    return f"{minutes:02d}:{secs:02d}.{centis:02d}"


class Athlete:
    def __init__(self, number: int, total_runs: int, total_questions: int, question_show_seconds: int):
        self.number = number
        self.total_runs = total_runs
        self.total_questions = total_questions
        self.question_show_seconds = question_show_seconds
        self.started = False
        self.finished = False
        self.start_time = None
        self.end_time = None
        self.completed_runs = 0
        self.splits = []
        self.cumulative_times = []
        self.last_split_abs = 0.0
        self.position_text = "Posizione run: -"
        self.current_question = "Prima pressione: CORRI"
        self.current_answer = ""
        self.question_history = []
        self.used_question_keys = set()
        self.current_level = "-"
        self.phase_text = "Attesa"
        self.question_visible_until = 0.0

    def elapsed_seconds(self) -> float:
        if not self.started:
            return 0.0
        if self.finished and self.end_time is not None:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    def elapsed_str(self) -> str:
        return format_time(self.elapsed_seconds())

    def is_question_visible(self) -> bool:
        return time.time() < self.question_visible_until


class QuestionManager:
    def __init__(self, question_bank):
        self.is_interdisciplinary = bool(question_bank.get("__interdisciplinary__")) if isinstance(question_bank, dict) else False
        if self.is_interdisciplinary:
            self.subject_banks = {
                subject: {level: items[:] for level, items in bank.items()}
                for subject, bank in question_bank.get("subjects", {}).items()
            }
            self.source_bank = None
        else:
            self.source_bank = question_bank
            self.subject_banks = {}
        self.interdisciplinary_plan = []
        self.reset()

    def reset(self):
        if self.is_interdisciplinary:
            self.banks = {
                subject: {level: items[:] for level, items in bank.items()}
                for subject, bank in self.subject_banks.items()
            }
            for bank in self.banks.values():
                for qs in bank.values():
                    random.shuffle(qs)
            self.indexes = {
                subject: {level: 0 for level in LEVELS}
                for subject in self.banks
            }
            return

        self.banks = {level: qs[:] for level, qs in self.source_bank.items()}
        for qs in self.banks.values():
            random.shuffle(qs)
        self.indexes = {level: 0 for level in self.banks}

    @staticmethod
    def _question_key(item):
        return (
            str(item.get("subject", "")).strip(),
            str(item.get("question", "")).strip(),
            str(item.get("answer", "")).strip()
        )

    def validate_unique_questions(self, total_questions: int):
        if self.is_interdisciplinary:
            return self.validate_interdisciplinary_setup(total_questions)

        required_by_level = {level: 0 for level in LEVELS}
        for question_number in range(1, total_questions + 1):
            level = self.level_for_question(question_number, total_questions)
            required_by_level[level] += 1

        missing = {}
        for level, required in required_by_level.items():
            available = len({self._question_key(item) for item in self.source_bank[level]})
            if available < required:
                missing[level] = {"required": required, "available": available}
        return missing

    def validate_interdisciplinary_setup(self, total_questions: int):
        subject_names = sorted(self.subject_banks.keys())
        if not subject_names:
            return {"error": "Nessuna materia disponibile per creare il percorso interdisciplinare."}

        if total_questions % len(subject_names) != 0:
            return {
                "error": (
                    f"Con {len(subject_names)} materie servono un numero di domande multiplo di {len(subject_names)} "
                    "per avere lo stesso numero di domande per materia."
                )
            }

        if total_questions % len(LEVELS) != 0:
            return {
                "error": (
                    f"Servono un numero di domande multiplo di {len(LEVELS)} "
                    "per avere lo stesso numero di domande per difficolta."
                )
            }

        pair_counts = self._build_interdisciplinary_pair_counts(total_questions)
        if pair_counts is None:
            return {
                "error": (
                    "Non riesco a bilanciare domande per materia e difficolta con le domande uniche "
                    "disponibili nei file JSON."
                )
            }

        self.interdisciplinary_plan = self._build_interdisciplinary_plan(pair_counts)
        return {}

    def _build_interdisciplinary_pair_counts(self, total_questions: int):
        subject_names = sorted(self.subject_banks.keys())
        per_subject = total_questions // len(subject_names)
        per_level = total_questions // len(LEVELS)
        capacities = {
            subject: {
                level: len({self._question_key(item) for item in self.subject_banks[subject][level]})
                for level in LEVELS
            }
            for subject in subject_names
        }

        def subject_allocations(subject: str, needed: int, level_index: int, col_remaining, current):
            if level_index == len(LEVELS):
                if needed == 0:
                    yield current.copy()
                return

            level = LEVELS[level_index]
            remaining_levels = len(LEVELS) - level_index - 1
            max_for_level = min(needed, col_remaining[level], capacities[subject][level])
            min_for_level = max(0, needed - sum(col_remaining[next_level] for next_level in LEVELS[level_index + 1:]))

            preferred = sorted(
                range(min_for_level, max_for_level + 1),
                key=lambda value: (abs(value - (needed / (remaining_levels + 1))), -value)
            )
            for value in preferred:
                current[level] = value
                next_remaining = col_remaining.copy()
                next_remaining[level] -= value
                yield from subject_allocations(subject, needed - value, level_index + 1, next_remaining, current)
            current.pop(level, None)

        def assign_subject(subject_index: int, col_remaining, matrix):
            if subject_index == len(subject_names):
                if all(col_remaining[level] == 0 for level in LEVELS):
                    return matrix
                return None

            subject = subject_names[subject_index]
            for allocation in subject_allocations(subject, per_subject, 0, col_remaining, {}):
                next_remaining = col_remaining.copy()
                for level, amount in allocation.items():
                    next_remaining[level] -= amount
                    if next_remaining[level] < 0:
                        break
                else:
                    next_matrix = {name: counts.copy() for name, counts in matrix.items()}
                    next_matrix[subject] = {level: allocation.get(level, 0) for level in LEVELS}
                    result = assign_subject(subject_index + 1, next_remaining, next_matrix)
                    if result is not None:
                        return result
            return None

        return assign_subject(0, {level: per_level for level in LEVELS}, {})

    def _build_interdisciplinary_plan(self, pair_counts):
        plan = []
        remaining = {
            subject: {level: pair_counts[subject][level] for level in LEVELS}
            for subject in pair_counts
        }
        subject_names = sorted(remaining.keys())
        while True:
            added_any = False
            for subject in subject_names:
                available_levels = [level for level in LEVELS if remaining[subject][level] > 0]
                if not available_levels:
                    continue
                available_levels.sort(key=lambda level: (-remaining[subject][level], LEVELS.index(level)))
                level = available_levels[0]
                plan.append((subject, level))
                remaining[subject][level] -= 1
                added_any = True
            if not added_any:
                break
        return plan

    def next_question(self, athlete: Athlete, question_number: int, total_questions: int):
        if self.is_interdisciplinary:
            return self._next_interdisciplinary_question(athlete, question_number)

        level = self.level_for_question(question_number, total_questions)
        questions = self.banks[level]
        start_idx = self.indexes[level]

        for offset in range(len(questions)):
            idx = (start_idx + offset) % len(questions)
            item = questions[idx]
            if self._question_key(item) not in athlete.used_question_keys:
                self.indexes[level] = idx + 1
                athlete.used_question_keys.add(self._question_key(item))
                return level, item["question"], item.get("answer", ""), item.get("subject", "")

        idx = start_idx % len(questions)
        self.indexes[level] += 1
        item = questions[idx]
        athlete.used_question_keys.add(self._question_key(item))
        return level, item["question"], item.get("answer", ""), item.get("subject", "")

    def _next_interdisciplinary_question(self, athlete: Athlete, question_number: int):
        subject, level = self.interdisciplinary_plan[question_number - 1]
        questions = self.banks[subject][level]
        start_idx = self.indexes[subject][level]

        for offset in range(len(questions)):
            idx = (start_idx + offset) % len(questions)
            item = questions[idx]
            if self._question_key(item) not in athlete.used_question_keys:
                self.indexes[subject][level] = idx + 1
                athlete.used_question_keys.add(self._question_key(item))
                return level, item["question"], item.get("answer", ""), subject

        idx = start_idx % len(questions)
        self.indexes[subject][level] += 1
        item = questions[idx]
        athlete.used_question_keys.add(self._question_key(item))
        return level, item["question"], item.get("answer", ""), subject

    @staticmethod
    def level_for_question(question_number: int, total_questions: int) -> str:
        if total_questions <= 1:
            return "Facile"
        ratio = question_number / total_questions
        if ratio <= 0.25:
            return "Facile"
        if ratio <= 0.50:
            return "Media"
        if ratio <= 0.75:
            return "Difficile"
        return "Plus"


class AthletePanel:
    def __init__(self, master, athlete: Athlete, compact: bool, ultra_compact: bool = False):
        self.athlete = athlete

        if ultra_compact:
            width = 420
            height = 300
            title_size = 13
            timer_size = 18
            badge_size = 9
            info_size = 9
            question_size = 9
            wrap = 390
            q_height = 10
        elif compact:
            width = 430
            height = 260
            title_size = 15
            timer_size = 24
            badge_size = 10
            info_size = 10
            question_size = 10
            wrap = 395
            q_height = 7
        else:
            width = 600
            height = 340
            title_size = 22
            timer_size = 36
            badge_size = 14
            info_size = 12
            question_size = 18
            wrap = 550
            q_height = 8
        self.question_wrap_pixels = max(120, wrap - 24)
        self.wrap_font = tkfont.Font(family="Arial", size=question_size + 2, weight="bold")

        self.frame = tk.Frame(master, bg="white", bd=3, relief="solid", width=width, height=height)
        self.frame.grid_propagate(False)
        self.frame.pack_propagate(False)

        inner = tk.Frame(self.frame, bg="white", padx=8, pady=8)
        inner.pack(fill="both", expand=True)

        self.title_var = tk.StringVar()
        self.time_var = tk.StringVar()
        self.run_var = tk.StringVar()
        self.level_var = tk.StringVar()
        self.position_var = tk.StringVar()
        self.question_var = tk.StringVar()
        self.phase_var = tk.StringVar()

        header_row = tk.Frame(inner, bg="white")
        header_row.pack(fill="x")

        self.header_label = tk.Label(header_row, textvariable=self.title_var, font=("Arial", title_size, "bold"), bg="white", anchor="w")
        self.header_label.pack(side="left", fill="x", expand=True)

        self.timer_label = tk.Label(header_row, textvariable=self.time_var, font=("Arial", timer_size, "bold"), bg="white", anchor="e")
        self.timer_label.pack(side="right")

        self.info_box = tk.Frame(inner, bg="white")
        self.info_box.pack(fill="both", expand=True)

        self.phase_label = tk.Label(self.info_box, textvariable=self.phase_var, font=("Arial", badge_size, "bold"), bg="#d9d9d9", padx=6, pady=4)
        self.phase_label.pack(fill="x", pady=(0, 6))

        info_row = tk.Frame(self.info_box, bg="white")
        info_row.pack(fill="x", pady=(0, 4))

        self.run_label = tk.Label(info_row, textvariable=self.run_var, font=("Arial", info_size, "bold"), bg="white", anchor="w")
        self.run_label.pack(side="left", padx=(0, 12))

        self.level_label = tk.Label(info_row, textvariable=self.level_var, font=("Arial", info_size, "bold"), bg="white", anchor="w")
        self.level_label.pack(side="left", padx=(0, 12))

        self.position_label = tk.Label(info_row, textvariable=self.position_var, font=("Arial", info_size, "bold"), bg="white", anchor="w", justify="left")
        self.position_label.pack(side="left", fill="x", expand=True)

        self.question_label = tk.Label(
            self.info_box,
            textvariable=self.question_var,
            font=("Arial", question_size, "bold"),
            bg="#f3f3f3",
            justify="left",
            anchor="nw",
            wraplength=wrap,
            padx=8,
            pady=8,
            height=q_height
        )
        self.question_label.pack(fill="both", expand=True)

        self.question_only_label = tk.Label(
            inner,
            textvariable=self.question_var,
            font=("Arial", question_size, "bold"),
            bg="#fff8db",
            justify="left",
            anchor="nw",
            wraplength=wrap,
            padx=24,
            pady=10,
            height=q_height + 1
        )

        self.refresh()

    def _wrap_question_text(self, text: str) -> str:
        wrapped = []
        for part in text.splitlines():
            chunk = part.strip()
            if not chunk:
                wrapped.append("")
                continue
            wrapped.extend(self._wrap_paragraph_pixels(chunk))
        return "\n".join(wrapped)

    def _wrap_paragraph_pixels(self, paragraph: str):
        words = paragraph.split()
        if not words:
            return [""]

        lines = []
        current = ""
        for word in words:
            if self.wrap_font.measure(word) > self.question_wrap_pixels:
                if current:
                    lines.append(current)
                    current = ""
                lines.extend(self._split_long_word_pixels(word))
                continue

            candidate = f"{current} {word}".strip()
            if self.wrap_font.measure(candidate) <= self.question_wrap_pixels:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word

        if current:
            lines.append(current)
        return lines

    def _split_long_word_pixels(self, word: str):
        chunks = []
        current = ""
        for ch in word:
            candidate = current + ch
            if self.wrap_font.measure(candidate) <= self.question_wrap_pixels:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = ch
        if current:
            chunks.append(current)
        return chunks

    def grid(self, row: int, column: int):
        self.frame.grid(row=row, column=column, padx=8, pady=8, sticky="nsew")

    def refresh(self):
        a = self.athlete
        show_question_only = a.is_question_visible() and (not a.finished)

        self.title_var.set(f"ATLETA {a.number}")
        self.time_var.set(a.elapsed_str())
        self.run_var.set(f"Run: {a.completed_runs}/{a.total_runs}")
        self.level_var.set(f"Livello: {a.current_level}")
        self.position_var.set(a.position_text)
        self.question_var.set(self._wrap_question_text(a.current_question))
        self.phase_var.set(f"Fase: {a.phase_text}")

        phase = a.phase_text.lower()
        question = a.current_question.upper()
        if a.finished or "COMPLETATA" in question:
            self.phase_label.config(bg="#e74c3c", fg="white")
            self.question_label.config(bg="#fdecea")
            self.question_only_label.config(bg="#fdecea")
        elif "CORRI" in question or "corr" in phase:
            self.phase_label.config(bg="#27ae60", fg="white")
            self.question_label.config(bg="#eaf7ee")
            self.question_only_label.config(bg="#eaf7ee")
        else:
            self.phase_label.config(bg="#f1c40f", fg="black")
            self.question_label.config(bg="#fff8db")
            self.question_only_label.config(bg="#fff8db")

        if show_question_only:
            if self.info_box.winfo_manager():
                self.info_box.pack_forget()
            if not self.question_only_label.winfo_manager():
                self.question_only_label.pack(fill="both", expand=True, pady=(8, 0))
        else:
            if self.question_only_label.winfo_manager():
                self.question_only_label.pack_forget()
            if not self.info_box.winfo_manager():
                self.info_box.pack(fill="both", expand=True)


class MindTrailApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MindTrail Challenge Demo")
        try:
            self.root.state("zoomed")
        except Exception:
            self.root.geometry("1920x1080")

        self.subject_banks = load_question_subjects()
        self.question_manager = None
        self.active_athletes = {}
        self.panels = {}
        self.serial_connection = None
        self.serial_port = PORTA_DEFAULT
        self.serial_port_combo = None
        self.serial_thread = None
        self.serial_stop_event = threading.Event()
        self.demo_active = False
        self.report_window = None
        self.report_button = None
        self.report_auto_opened = False
        self.total_runs = 9
        self.total_questions = 8
        self.question_show_seconds = 9
        self.build_setup_ui()

    def build_setup_ui(self):
        self.subject_banks = load_question_subjects()
        self.setup_frame = tk.Frame(self.root, bg="white")
        self.setup_frame.pack(fill="both", expand=True)

        tk.Label(self.setup_frame, text="MindTrail Challenge - Demo collegio docenti", font=("Arial", 30, "bold"), bg="white").pack(pady=(25, 30))

        row1 = tk.Frame(self.setup_frame, bg="white")
        row1.pack(pady=15)
        tk.Label(row1, text="Numero partecipanti (1-12)", font=("Arial", 20, "bold"), bg="white").pack(side="left", padx=12)
        self.participants_var = tk.IntVar(value=4)
        tk.Spinbox(row1, from_=1, to=12, textvariable=self.participants_var, width=6, font=("Arial", 22), justify="center").pack(side="left", padx=12)

        row_subject = tk.Frame(self.setup_frame, bg="white")
        row_subject.pack(pady=15)
        tk.Label(row_subject, text="Materia", font=("Arial", 20, "bold"), bg="white").pack(side="left", padx=12)
        subject_names = sorted(self.subject_banks.keys())
        default_subject = subject_names[0] if subject_names else ""
        self.subject_var = tk.StringVar(value=default_subject)
        self.subject_combo = ttk.Combobox(
            row_subject,
            textvariable=self.subject_var,
            values=subject_names,
            state="readonly",
            width=28,
            font=("Arial", 18),
            justify="center"
        )
        self.subject_combo.pack(side="left", padx=12)

        row2 = tk.Frame(self.setup_frame, bg="white")
        row2.pack(pady=15)
        tk.Label(row2, text="Numero domande per atleta (1-24)", font=("Arial", 20, "bold"), bg="white").pack(side="left", padx=12)
        self.questions_var = tk.IntVar(value=8)
        tk.Spinbox(row2, from_=1, to=24, textvariable=self.questions_var, width=6, font=("Arial", 22), justify="center").pack(side="left", padx=12)

        row3 = tk.Frame(self.setup_frame, bg="white")
        row3.pack(pady=15)
        tk.Label(row3, text="Numero run per atleta (2-25)", font=("Arial", 20, "bold"), bg="white").pack(side="left", padx=12)
        self.runs_var = tk.IntVar(value=9)
        tk.Spinbox(row3, from_=2, to=25, textvariable=self.runs_var, width=6, font=("Arial", 22), justify="center").pack(side="left", padx=12)

        row4 = tk.Frame(self.setup_frame, bg="white")
        row4.pack(pady=15)
        tk.Label(row4, text="Mostra la domanda per quanti secondi", font=("Arial", 20, "bold"), bg="white").pack(side="left", padx=12)
        self.question_seconds_var = tk.IntVar(value=9)
        tk.Spinbox(row4, from_=3, to=20, textvariable=self.question_seconds_var, width=6, font=("Arial", 22), justify="center").pack(side="left", padx=12)

        row5 = tk.Frame(self.setup_frame, bg="white")
        row5.pack(pady=15)
        tk.Label(row5, text="Porta seriale (es. COM12)", font=("Arial", 20, "bold"), bg="white").pack(side="left", padx=12)
        self.serial_port_var = tk.StringVar(value=PORTA_DEFAULT)
        self.serial_port_combo = ttk.Combobox(row5, textvariable=self.serial_port_var, width=12, state="normal", justify="center")
        self.serial_port_combo.pack(side="left", padx=12)
        tk.Button(row5, text="Aggiorna porte", font=("Arial", 12, "bold"), command=self.refresh_serial_ports, bg="#2ea043", fg="white").pack(side="left", padx=8)

        self.serial_ports_hint_var = tk.StringVar(value="")
        tk.Label(self.setup_frame, textvariable=self.serial_ports_hint_var, font=("Arial", 11), bg="white", fg="#555").pack()

        self.refresh_serial_ports(initial=True)

        if not self.subject_banks:
            tk.Label(
                self.setup_frame,
                text="Nessuna materia trovata in cartella 'questions'. Aggiungi almeno un file JSON valido.",
                font=("Arial", 14, "bold"),
                bg="white",
                fg="#b91c1c"
            ).pack(pady=(8, 0))

        tk.Button(self.setup_frame, text="Avvia demo", font=("Arial", 20, "bold"), command=self.start_demo, width=18, height=2, bg="#1f6feb", fg="white").pack(pady=30)

        tk.Label(
            self.setup_frame,
            text=(
                "Quando appare la domanda, per il tempo scelto scompaiono le altre info della scheda.\n"
                "Scaduto il tempo, riappaiono tempo, livello, posizione e fase."
            ),
            font=("Arial", 16, "bold"),
            bg="white",
            justify="center"
        ).pack(pady=(10, 0))

    def start_demo(self):
        selected_subject = self.subject_var.get().strip()
        selected_bank = self.subject_banks.get(selected_subject)
        if not selected_bank:
            messagebox.showerror(
                "Materia non disponibile",
                "Seleziona una materia valida oppure aggiungi file JSON in cartella 'questions'."
            )
            return

        count = max(1, min(NUM_MAX_ATLETI, self.participants_var.get()))
        requested_questions = max(1, min(24, self.questions_var.get()))
        self.total_runs = max(2, min(25, self.runs_var.get()))
        self.total_questions = min(requested_questions, self.total_runs - 1)
        self.question_show_seconds = max(3, min(20, self.question_seconds_var.get()))
        self.serial_port = (self.serial_port_var.get().strip() or PORTA_DEFAULT).upper()

        if USE_SERIAL and serial is not None and (not self._is_valid_serial_port(self.serial_port)):
            messagebox.showerror(
                "Porta seriale non valida",
                "Inserisci una porta valida nel formato COMx (es. COM12)."
            )
            return

        self.question_manager = QuestionManager(selected_bank)
        missing_questions = self.question_manager.validate_unique_questions(self.total_questions)
        if missing_questions:
            if "error" in missing_questions:
                details = missing_questions["error"]
            else:
                details = ", ".join(
                    f"{level}: servono {data['required']}, disponibili {data['available']}"
                    for level, data in missing_questions.items()
                )
            messagebox.showerror(
                "Domande insufficienti",
                "La materia selezionata non ha abbastanza domande uniche o non consente il bilanciamento "
                f"richiesto per questa gara.\n\n{details}"
            )
            self.question_manager = None
            return

        self.question_manager.reset()
        self.setup_frame.destroy()
        self.demo_active = True
        self.serial_stop_event.clear()
        self.report_auto_opened = False

        if self.report_window is not None and self.report_window.winfo_exists():
            self.report_window.destroy()
        self.report_window = None

        self.active_athletes = {
            i: Athlete(i, self.total_runs, self.total_questions, self.question_show_seconds)
            for i in range(1, count + 1)
        }

        self.main_frame = tk.Frame(self.root, bg="#f4f4f4")
        self.main_frame.pack(fill="both", expand=True)

        header = tk.Frame(self.main_frame, bg="#f4f4f4", height=56)
        header.pack(fill="x", pady=(6, 8))
        header.pack_propagate(False)
        header_right = tk.Frame(header, bg="#f4f4f4")
        header_right.pack(side="right", padx=10)
        tk.Button(
            header_right,
            text="Torna al setup / Riavvia",
            font=("Arial", 12, "bold"),
            command=self.back_to_setup,
            bg="#ef4444",
            fg="white"
        ).pack(side="right")
        self.report_button = tk.Button(
            header_right,
            text="Report finale",
            font=("Arial", 12, "bold"),
            command=self.show_final_report,
            bg="#2563eb",
            fg="white",
            state="disabled"
        )
        self.report_button.pack(side="right", padx=(0, 8))

        header_left = tk.Frame(header, bg="#f4f4f4")
        header_left.pack(side="left", fill="x", expand=True)
        tk.Label(header_left, text="MINDTRAIL CHALLENGE", font=("Arial", 26, "bold"), bg="#f4f4f4").pack(side="left", padx=8)
        tk.Label(header_left, text=f"Partecipanti: {count}", font=("Arial", 16, "bold"), bg="#f4f4f4").pack(side="left", padx=10)
        tk.Label(header_left, text=f"Materia: {selected_subject}", font=("Arial", 16, "bold"), bg="#f4f4f4").pack(side="left", padx=10)
        tk.Label(header_left, text=f"Domande: {self.total_questions}", font=("Arial", 16, "bold"), bg="#f4f4f4").pack(side="left", padx=10)
        tk.Label(header_left, text=f"Run: {self.total_runs}", font=("Arial", 16, "bold"), bg="#f4f4f4").pack(side="left", padx=10)
        tk.Label(header_left, text=f"Show: {self.question_show_seconds}s", font=("Arial", 16, "bold"), bg="#f4f4f4").pack(side="left", padx=24)

        self.grid_frame = tk.Frame(self.main_frame, bg="#f4f4f4")
        self.grid_frame.pack(fill="both", expand=True, padx=6, pady=6)

        ultra_compact = False
        if count >= 10:
            columns = 4
            compact = True
            ultra_compact = True
        elif count >= 7:
            columns = 3
            compact = True
        elif count >= 5:
            columns = 3
            compact = False
        elif count >= 4:
            columns = 2
            compact = True
        else:
            columns = 2
            compact = False

        rows = (count + columns - 1) // columns
        for c in range(columns):
            self.grid_frame.grid_columnconfigure(c, weight=1, uniform="col")
        for r in range(rows):
            self.grid_frame.grid_rowconfigure(r, weight=1, uniform="row")

        for idx, athlete in enumerate(self.active_athletes.values()):
            panel = AthletePanel(self.grid_frame, athlete, compact=compact, ultra_compact=ultra_compact)
            panel.grid(idx // columns, idx % columns)
            self.panels[athlete.number] = panel

        self.root.after(10, self.refresh_timers)
        self.start_serial_thread()

    def _get_available_serial_ports(self):
        if serial is None:
            return []
        try:
            from serial.tools import list_ports

            ports = [p.device.upper() for p in list_ports.comports()]
            ports = [p for p in ports if self._is_valid_serial_port(p)]
            return sorted(set(ports), key=lambda p: int(p[3:]))
        except Exception:
            return []

    def refresh_serial_ports(self, initial: bool = False):
        ports = self._get_available_serial_ports()
        current = (self.serial_port_var.get().strip() or PORTA_DEFAULT).upper()

        if self.serial_port_combo is not None:
            self.serial_port_combo["values"] = ports

        if ports:
            if current not in ports:
                self.serial_port_var.set(PORTA_DEFAULT if (initial and PORTA_DEFAULT in ports) else ports[0])
            self.serial_ports_hint_var.set(f"Porte trovate: {', '.join(ports)}")
        else:
            if initial and not self.serial_port_var.get().strip():
                self.serial_port_var.set(PORTA_DEFAULT)
            self.serial_ports_hint_var.set("Nessuna porta rilevata automaticamente. Inserisci COMx manualmente.")

    @staticmethod
    def _is_valid_serial_port(port: str) -> bool:
        return re.fullmatch(r"COM[1-9][0-9]*", port.upper()) is not None

    def start_serial_thread(self):
        if not USE_SERIAL or serial is None:
            return
        if self.serial_thread is not None and self.serial_thread.is_alive():
            return
        self.serial_thread = threading.Thread(target=self.read_serial, daemon=True)
        self.serial_thread.start()

    def read_serial(self):
        try:
            self.serial_connection = serial.Serial(self.serial_port, BAUD, timeout=1)
            time.sleep(2)
            print(f"COLLEGATO A {self.serial_port}")
            while not self.serial_stop_event.is_set():
                line = self.serial_connection.readline().decode(errors="ignore").strip()
                if not line:
                    continue
                if line.startswith("PULSANTE:"):
                    try:
                        number = int(line.split(":")[1].strip())
                        self.root.after(0, lambda n=number: self.handle_press(n))
                    except ValueError:
                        pass
        except Exception as e:
            if self.serial_stop_event.is_set():
                return
            print("ERRORE SERIALE:", e)
        finally:
            if self.serial_connection is not None:
                try:
                    self.serial_connection.close()
                except Exception:
                    pass
                self.serial_connection = None

    def handle_press(self, athlete_number: int):
        if athlete_number not in self.active_athletes:
            return

        athlete = self.active_athletes[athlete_number]
        self.advance_athlete(athlete)
        self.update_positions()
        self.panels[athlete_number].refresh()

    def advance_athlete(self, athlete: Athlete):
        now = time.time()

        if athlete.finished:
            return

        if not athlete.started:
            athlete.started = True
            athlete.start_time = now
            athlete.phase_text = "Sta correndo verso la domanda 1"
            athlete.current_level = "-"
            athlete.current_question = "CORRI"
            athlete.question_visible_until = 0.0
            return

        absolute = now - athlete.start_time
        split = absolute - athlete.last_split_abs
        athlete.last_split_abs = absolute
        athlete.splits.append(split)
        athlete.cumulative_times.append(absolute)
        athlete.completed_runs += 1

        if athlete.completed_runs <= athlete.total_questions:
            qn = athlete.completed_runs
            level, question, answer, subject = self.question_manager.next_question(athlete, qn, athlete.total_questions)
            athlete.current_level = level
            athlete.phase_text = f"Rispondi alla domanda {qn}"
            if subject and self.subject_var.get().strip() == INTERDISCIPLINARY_SUBJECT:
                athlete.current_question = f"Domanda {qn} - {subject}:\n{question}"
            else:
                athlete.current_question = f"Domanda {qn}:\n{question}"
            athlete.current_answer = answer
            athlete.question_history.append(
                {
                    "number": qn,
                    "subject": subject,
                    "level": level,
                    "question": question,
                    "answer": answer
                }
            )
            athlete.question_visible_until = time.time() + athlete.question_show_seconds
            return

        if athlete.completed_runs < athlete.total_runs:
            athlete.current_level = "-"
            athlete.phase_text = "Ultima corsa verso il traguardo finale"
            athlete.current_question = "CORRI VERSO IL TRAGUARDO FINALE"
            athlete.question_visible_until = 0.0
            return

        athlete.finished = True
        athlete.end_time = now
        athlete.current_level = "-"
        athlete.phase_text = "Gara terminata"
        athlete.current_question = "GARA COMPLETATA"
        athlete.question_visible_until = 0.0

    def update_positions(self):
        max_run = max((a.completed_runs for a in self.active_athletes.values()), default=0)
        for run_no in range(1, max_run + 1):
            completed = []
            for athlete in self.active_athletes.values():
                if len(athlete.cumulative_times) >= run_no:
                    completed.append((athlete, athlete.cumulative_times[run_no - 1]))
            completed.sort(key=lambda x: (x[1], x[0].number))
            total_completed = len(completed)
            total_expected = len(self.active_athletes)
            for pos, (athlete, _) in enumerate(completed, start=1):
                if athlete.completed_runs == run_no:
                    if total_completed == total_expected:
                        athlete.position_text = f"Posizione: {pos}\u00b0 su {total_expected} (definitiva)"
                    else:
                        athlete.position_text = f"Posizione: {pos}\u00b0 su {total_completed} (provvisoria)"

        if self.report_button is not None:
            self.report_button.config(state=("normal" if self.all_athletes_finished() else "disabled"))

        if self.all_athletes_finished() and (not self.report_auto_opened):
            self.report_auto_opened = True
            self.show_final_report()

    def all_athletes_finished(self) -> bool:
        return bool(self.active_athletes) and all(a.finished for a in self.active_athletes.values())

    def _athlete_report_text(self, athlete: Athlete) -> str:
        lines = [f"ATLETA {athlete.number}", ""]
        if not athlete.question_history:
            lines.append("Nessuna domanda registrata.")
            return "\n".join(lines)

        for item in athlete.question_history:
            if item.get("subject"):
                lines.append(f"Domanda {item['number']} - Materia: {item['subject']} - Livello: {item['level']}")
            else:
                lines.append(f"Domanda {item['number']} - Livello: {item['level']}")
            lines.append(item["question"])
            lines.append(f"Risposta corretta: {item['answer'] or '(non disponibile)'}")
            lines.append("Risposta partecipante: ______________________________")
            lines.append("")
        return "\n".join(lines)

    def _athlete_answers_only_text(self, athlete: Athlete) -> str:
        lines = [f"ATLETA {athlete.number}", ""]
        if not athlete.question_history:
            lines.append("Nessuna risposta corretta registrata.")
            return "\n".join(lines)

        for item in athlete.question_history:
            prefix = f"{item['number']}."
            if item.get("subject"):
                prefix += f" [{item['subject']}]"
            lines.append(f"{prefix} {item['answer'] or '(non disponibile)'}")
        return "\n".join(lines)

    def _answers_only_report_text(self) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "MINDTRAIL CHALLENGE - RISPOSTE ESATTE",
            f"Generato il: {stamp}",
            ""
        ]
        for athlete in sorted(self.active_athletes.values(), key=lambda a: a.number):
            lines.append(self._athlete_answers_only_text(athlete))
            lines.append("-" * 50)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _full_report_text(self) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "MINDTRAIL CHALLENGE - REPORT FINALE",
            f"Generato il: {stamp}",
            ""
        ]
        for athlete in sorted(self.active_athletes.values(), key=lambda a: a.number):
            lines.append(self._athlete_report_text(athlete))
            lines.append("-" * 80)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _athlete_total_time_str(self, athlete: Athlete) -> str:
        if athlete.finished and athlete.end_time is not None:
            return format_time(athlete.end_time - athlete.start_time)
        if athlete.started:
            return format_time(athlete.elapsed_seconds())
        return "-"

    def _athlete_status_text(self, athlete: Athlete) -> str:
        if athlete.finished:
            return "Completata"
        if athlete.started:
            return "In corso"
        return "Non partita"

    def _classifica_report_text(self) -> str:
        athletes = sorted(
            self.active_athletes.values(),
            key=lambda a: (
                0 if a.finished else 1,
                (a.end_time - a.start_time) if (a.finished and a.end_time is not None) else float("inf"),
                -a.completed_runs,
                a.number
            )
        )

        lines = [
            "CLASSIFICA FINALE",
            "",
            "Pos | Atleta | Stato       | Tempo Tot | Run         | Domande | Split medio | Miglior split | Peggior split",
            "-" * 110
        ]

        for pos, athlete in enumerate(athletes, start=1):
            splits = athlete.splits[:] if athlete.splits else []
            avg_split = format_time(sum(splits) / len(splits)) if splits else "-"
            best_split = format_time(min(splits)) if splits else "-"
            worst_split = format_time(max(splits)) if splits else "-"
            lines.append(
                f"{pos:>3} | "
                f"{athlete.number:>6} | "
                f"{self._athlete_status_text(athlete):<11} | "
                f"{self._athlete_total_time_str(athlete):>8} | "
                f"{athlete.completed_runs:>3}/{athlete.total_runs:<10} | "
                f"{len(athlete.question_history):>7} | "
                f"{avg_split:>11} | "
                f"{best_split:>13} | "
                f"{worst_split:>13}"
            )

        lines.append("")
        lines.append("Dettaglio atleta:")
        for athlete in athletes:
            lines.append(
                f"- Atleta {athlete.number}: "
                f"tempo={self._athlete_total_time_str(athlete)}, "
                f"stato={self._athlete_status_text(athlete)}, "
                f"domande visualizzate={len(athlete.question_history)}, "
                f"run completati={athlete.completed_runs}/{athlete.total_runs}"
            )

        return "\n".join(lines)

    def _full_report_html(self) -> str:
        import html

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        blocks = [f"<h2>Classifica finale</h2><p>{html.escape(self._classifica_report_text()).replace(chr(10), '<br>')}</p>"]
        for athlete in sorted(self.active_athletes.values(), key=lambda a: a.number):
            content = html.escape(self._athlete_report_text(athlete)).replace("\n", "<br>")
            blocks.append(f"<h2>Atleta {athlete.number}</h2><p>{content}</p>")
        body = "\n".join(blocks)
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>MindTrail Report Finale</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; }}
    h1 {{ margin-bottom: 4px; }}
    h2 {{ margin-top: 28px; margin-bottom: 8px; }}
    p {{ line-height: 1.4; }}
    @media print {{ button {{ display: none; }} }}
  </style>
</head>
<body>
  <h1>MINDTRAIL CHALLENGE - REPORT FINALE</h1>
  <div>Generato il: {html.escape(stamp)}</div>
  {body}
</body>
</html>
"""

    def export_report_txt(self):
        if not self.active_athletes:
            return
        default_name = f"mindtrail_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_path = filedialog.asksaveasfilename(
            title="Salva report TXT",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("File di testo", "*.txt"), ("Tutti i file", "*.*")]
        )
        if not file_path:
            return
        try:
            Path(file_path).write_text(self._full_report_text(), encoding="utf-8")
            messagebox.showinfo("Export completato", f"Report salvato in:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Errore export", f"Impossibile salvare il report:\n{e}")

    def export_report_html(self):
        if not self.active_athletes:
            return
        default_name = f"mindtrail_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        file_path = filedialog.asksaveasfilename(
            title="Salva report HTML",
            defaultextension=".html",
            initialfile=default_name,
            filetypes=[("File HTML", "*.html"), ("Tutti i file", "*.*")]
        )
        if not file_path:
            return
        try:
            Path(file_path).write_text(self._full_report_html(), encoding="utf-8")
            messagebox.showinfo("Export completato", f"Report HTML salvato in:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Errore export", f"Impossibile salvare il report:\n{e}")

    def print_report_windows(self):
        if not self.active_athletes:
            return
        if os.name != "nt":
            messagebox.showinfo("Stampa", "Stampa rapida disponibile solo su Windows.")
            return
        try:
            temp_dir = Path(tempfile.gettempdir())
            tmp_file = temp_dir / f"mindtrail_report_{int(time.time())}.html"
            tmp_file.write_text(self._full_report_html(), encoding="utf-8")
            os.startfile(str(tmp_file), "print")
            messagebox.showinfo("Stampa", "Comando di stampa inviato all'app predefinita.")
        except Exception as e:
            messagebox.showerror("Errore stampa", f"Impossibile avviare la stampa:\n{e}")

    def show_final_report(self):
        if not self.active_athletes:
            return

        if self.report_window is not None and self.report_window.winfo_exists():
            self.report_window.lift()
            self.report_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        win.title("Report Finale - Domande e Risposte")
        win.geometry("1100x760")
        win.configure(bg="white")
        self.report_window = win

        top = tk.Frame(win, bg="white")
        top.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(
            top,
            text="Report finale per atleta (domande proposte e risposte corrette)",
            font=("Arial", 16, "bold"),
            bg="white"
        ).pack(side="left")
        actions = tk.Frame(top, bg="white")
        actions.pack(side="right")
        tk.Button(actions, text="Esporta TXT", font=("Arial", 11, "bold"), command=self.export_report_txt, bg="#2563eb", fg="white").pack(side="left", padx=4)
        tk.Button(actions, text="Esporta HTML", font=("Arial", 11, "bold"), command=self.export_report_html, bg="#1d4ed8", fg="white").pack(side="left", padx=4)
        tk.Button(actions, text="Stampa", font=("Arial", 11, "bold"), command=self.print_report_windows, bg="#374151", fg="white").pack(side="left", padx=4)

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        classifica_tab = tk.Frame(notebook, bg="white")
        notebook.add(classifica_tab, text="Classifica finale")
        classifica_text = tk.Text(classifica_tab, wrap="none", font=("Consolas", 11), padx=10, pady=10)
        classifica_scroll_y = tk.Scrollbar(classifica_tab, orient="vertical", command=classifica_text.yview)
        classifica_scroll_x = tk.Scrollbar(classifica_tab, orient="horizontal", command=classifica_text.xview)
        classifica_text.configure(yscrollcommand=classifica_scroll_y.set, xscrollcommand=classifica_scroll_x.set)
        classifica_text.pack(side="left", fill="both", expand=True)
        classifica_scroll_y.pack(side="right", fill="y")
        classifica_scroll_x.pack(side="bottom", fill="x")
        classifica_text.insert("1.0", self._classifica_report_text())
        classifica_text.configure(state="disabled")

        answers_tab = tk.Frame(notebook, bg="white")
        notebook.add(answers_tab, text="Solo risposte esatte")
        answers_text = tk.Text(answers_tab, wrap="word", font=("Arial", 13), padx=12, pady=12)
        answers_scroll = tk.Scrollbar(answers_tab, orient="vertical", command=answers_text.yview)
        answers_text.configure(yscrollcommand=answers_scroll.set)
        answers_text.pack(side="left", fill="both", expand=True)
        answers_scroll.pack(side="right", fill="y")
        answers_text.insert("1.0", self._answers_only_report_text())
        answers_text.configure(state="disabled")

        for athlete in sorted(self.active_athletes.values(), key=lambda a: a.number):
            tab = tk.Frame(notebook, bg="white")
            notebook.add(tab, text=f"Atleta {athlete.number}")

            text = tk.Text(tab, wrap="word", font=("Arial", 12), padx=10, pady=10)
            scroll = tk.Scrollbar(tab, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            text.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")

            text.insert("1.0", self._athlete_report_text(athlete))
            text.configure(state="disabled")

    def refresh_timers(self):
        if not self.demo_active:
            return
        for athlete_no, athlete in self.active_athletes.items():
            if athlete.started:
                self.panels[athlete_no].refresh()
        self.root.after(10, self.refresh_timers)

    def back_to_setup(self):
        self.demo_active = False
        self.serial_stop_event.set()
        if self.serial_connection is not None:
            try:
                self.serial_connection.close()
            except Exception:
                pass
            self.serial_connection = None

        if hasattr(self, "main_frame") and self.main_frame.winfo_exists():
            self.main_frame.destroy()
        if self.report_window is not None and self.report_window.winfo_exists():
            self.report_window.destroy()
        self.report_window = None
        self.report_button = None

        self.active_athletes = {}
        self.panels = {}
        if self.question_manager is not None:
            self.question_manager.reset()
        self.build_setup_ui()


if __name__ == "__main__":
    root = tk.Tk()
    app = MindTrailApp(root)
    root.mainloop()
