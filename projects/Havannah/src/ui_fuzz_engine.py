#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import random
import sys
import time
import traceback
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


CoverageKey = Tuple[Any, ...]

STRUCTURE_NAMES = {
    0: "none",
    1: "bridge",
    2: "fork",
    3: "ring",
}

AXIAL_DIRECTIONS = [
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
]

MODES = [
    "random_raw",
    "valid_random",
    "coverage_guided",
    "coverage_guided_rate",
    "rgr_positive",
    "rgr_positive_rate",
    "anti_rgr_negative",
    "anti_rgr_negative_rate",
]

TARGETS = [
    "model",
    "gui",
]


@dataclass
class CorpusEntry:
    board_size: int
    moves: List[int]
    gain: int = 0
    executions: int = 0
    created_at_iteration: int = 0
    total_time: float = 0.0
    coverage_found: int = 0
    bugs_found: int = 0


@dataclass
class RunResult:
    target: str
    initial_board_size: int
    board_size: int
    raw_moves: List[int]
    actual_moves: List[int]
    coverage: Set[CoverageKey]
    steps_executed: int
    done: bool
    winner: int
    win_kind: int
    move_count: int
    elapsed_seconds: float

    bug_id: Optional[str] = None
    base_bug_id: Optional[str] = None
    bug_variant_source: str = ""
    bug_message: str = ""

    last_action: str = ""
    last_event: str = ""

    gui_events_executed: int = 0
    gui_valid_clicks: int = 0
    gui_occupied_clicks: int = 0
    gui_redraws: int = 0
    gui_status_updates: int = 0
    gui_resets: int = 0


def load_wrapper():
    here = Path(__file__).resolve()

    candidate_build_dirs = [
        here.parent.parent / "build",
        here.parent / "build",
        Path.cwd() / "build",
    ]

    for build_dir in candidate_build_dirs:
        wrapper_path = build_dir / "wrapper.py"
        if wrapper_path.exists():
            sys.path.insert(0, str(build_dir))
            import wrapper  # type: ignore

            return wrapper

    searched = "\n".join(str(p / "wrapper.py") for p in candidate_build_dirs)
    raise FileNotFoundError(
        "wrapper.py non trovato.\n"
        "Prima compila il progetto con:\n"
        "  ./run.sh build\n\n"
        f"Percorsi cercati:\n{searched}"
    )


def load_gui_module(gui_file: Optional[Path] = None):
    here = Path(__file__).resolve()
    candidates: List[Path] = []

    if gui_file is not None:
        candidates.append(gui_file)
        if not gui_file.is_absolute():
            candidates.append(Path.cwd() / gui_file)
            candidates.append(here.parent / gui_file.name)

    candidates.extend(
        [
            here.parent / "gui.py",
            Path.cwd() / "src" / "gui.py",
            Path.cwd() / "gui.py",
        ]
    )

    seen: Set[str] = set()
    unique_candidates: List[Path] = []

    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(candidate)

    for gui_path in unique_candidates:
        if gui_path.exists():
            spec = importlib.util.spec_from_file_location(
                "havannah_gui_under_test",
                gui_path,
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Impossibile creare spec per {gui_path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules["havannah_gui_under_test"] = module
            spec.loader.exec_module(module)
            return module

    searched = "\n".join(str(p) for p in unique_candidates)
    raise FileNotFoundError(f"Modulo GUI non trovato. Percorsi cercati:\n{searched}")


class UIFuzzEngine:
    def __init__(
        self,
        target: str,
        mode: str,
        iterations: int,
        time_budget_seconds: Optional[float],
        board_sizes: Sequence[int],
        max_len: int,
        seed: Optional[int],
        out_dir: Path,
        report_every: int,
        mutation_rounds: int,
        run_id: str,
        enable_injected_bugs: bool,
        enable_model_invariants: bool,
        gui_file: Optional[Path],
        bug_variant_mod: int,
    ):
        if target not in TARGETS:
            raise ValueError(f"Target sconosciuto: {target}")
        if mode not in MODES:
            raise ValueError(f"Modalità sconosciuta: {mode}")

        self.wrapper = load_wrapper()

        self.target = target
        self.mode = mode
        self.iterations = iterations
        self.time_budget_seconds = time_budget_seconds
        self.board_sizes = list(board_sizes)
        self.max_len = max_len
        self.out_dir = out_dir
        self.report_every = report_every
        self.mutation_rounds = mutation_rounds
        self.run_id = run_id
        self.enable_injected_bugs = enable_injected_bugs
        self.enable_model_invariants = enable_model_invariants
        self.gui_file = gui_file
        self.bug_variant_mod = bug_variant_mod

        self.rng = random.Random(seed)
        self.seed = seed

        self.global_coverage: Set[CoverageKey] = set()
        self.bugs_found: Set[str] = set()
        self.base_bugs_found: Set[str] = set()

        self.corpus: List[CorpusEntry] = self._build_initial_corpus()

        self.stats = Counter()
        self.best_gain = 0
        self.start_time = 0.0

        self.timeline_file = None
        self.timeline_writer = None

        self.gui_module = None
        self.gui_app = None

        if self.target == "gui":
            self.gui_module = load_gui_module(self.gui_file)
            self.gui_app = self._create_gui_app_for_fuzzing()

    def _build_initial_corpus(self) -> List[CorpusEntry]:
        corpus: List[CorpusEntry] = []
        seed_lengths = [0, 5, 10, 20, 40]
        unique_lengths = sorted({min(length, self.max_len) for length in seed_lengths})

        for size in self.board_sizes:
            for length in unique_lengths:
                moves = [self._random_raw_move() for _ in range(length)]
                corpus.append(
                    CorpusEntry(
                        board_size=size,
                        moves=moves,
                        gain=1,
                        created_at_iteration=0,
                    )
                )

        return corpus

    # ============================================================
    # SETUP GUI
    # ============================================================

    def _create_gui_app_for_fuzzing(self):
        assert self.gui_module is not None

        initial_size = self.board_sizes[-1] if self.board_sizes else 8

        try:
            try:
                app = self.gui_module.HavannahGUI(
                    initial_board_size=initial_size,
                    test_mode=True,
                    show_window=False,
                    enable_injected_bugs=self.enable_injected_bugs,
                )
            except TypeError:
                app = self.gui_module.HavannahGUI(
                    initial_board_size=initial_size,
                    test_mode=True,
                    show_window=False,
                )
        except Exception as exc:
            raise RuntimeError(
                "Impossibile creare la GUI Tkinter. "
                "Il target gui richiede un ambiente con display grafico attivo."
            ) from exc

        return app

    def _destroy_gui_app(self):
        if self.gui_app is not None:
            try:
                self.gui_app.root.destroy()
            except Exception:
                pass
            self.gui_app = None

    # ============================================================
    # RULEBOOK HELPERS
    # ============================================================

    def _bounded(self, class_name: str, value: int):
        cls = getattr(self.wrapper, class_name)
        obj = cls()
        obj.value = int(value)
        return obj

    def _new_session(self, board_size: int):
        session = self.wrapper.session()

        size_arg = self._bounded("BIntT3T8T", board_size)
        if not session.can_choose_board_size(size_arg):
            raise ValueError(f"Board size non valida per il wrapper: {board_size}")

        session.choose_board_size(size_arg)
        board = session.game.board
        return session, board

    # ============================================================
    # BOARD HELPERS
    # ============================================================

    def _valid_moves(self, board) -> List[int]:
        if board.is_done_game():
            return []

        return [i for i in range(board.cell_count()) if board.get_cell(i) == 0]

    def _occupied_moves(self, board) -> List[int]:
        return [i for i in range(board.cell_count()) if board.get_cell(i) in (1, 2)]

    def _cell_coords(self, board) -> Dict[int, Tuple[int, int]]:
        return {
            i: (board.cell_q(i), board.cell_r(i))
            for i in range(board.cell_count())
        }

    def _coord_to_index(self, board) -> Dict[Tuple[int, int], int]:
        return {
            (board.cell_q(i), board.cell_r(i)): i
            for i in range(board.cell_count())
        }

    def _corner_id(self, q: int, r: int, radius: int) -> int:
        if q == radius and r == 0:
            return 0
        if q == 0 and r == radius:
            return 1
        if q == -radius and r == radius:
            return 2
        if q == -radius and r == 0:
            return 3
        if q == 0 and r == -radius:
            return 4
        if q == radius and r == -radius:
            return 5
        return -1

    def _edge_id(self, q: int, r: int, radius: int) -> int:
        if self._corner_id(q, r, radius) != -1:
            return -1

        if q == radius:
            return 0
        if q + r == radius:
            return 1
        if r == -radius:
            return 2
        if q == -radius:
            return 3
        if q + r == -radius:
            return 4
        if r == radius:
            return 5

        return -1

    def _region_of_cell(self, board, board_size: int, index: int) -> Tuple[str, int]:
        q = int(board.cell_q(index))
        r = int(board.cell_r(index))
        radius = board_size - 1

        corner = self._corner_id(q, r, radius)
        if corner != -1:
            return "corner", corner

        edge = self._edge_id(q, r, radius)
        if edge != -1:
            return "edge", edge

        return "inside", -1

    def _bucket(self, value: int) -> int:
        boundaries = [0, 1, 2, 3, 4, 5, 8, 12, 20, 32, 50, 80, 120, 169]
        for b in boundaries:
            if value <= b:
                return b
        return 999

    # ============================================================
    # COVERAGE
    # ============================================================

    def _board_features(self, board, board_size: int) -> Dict[str, Any]:
        radius = board_size - 1

        stone_counts = {1: 0, 2: 0}
        edge_masks = {1: 0, 2: 0}
        corner_masks = {1: 0, 2: 0}

        for i in range(board.cell_count()):
            state = board.get_cell(i)
            if state not in (1, 2):
                continue

            stone_counts[state] += 1

            q = board.cell_q(i)
            r = board.cell_r(i)

            corner = self._corner_id(q, r, radius)
            if corner != -1:
                corner_masks[state] |= 1 << corner

            edge = self._edge_id(q, r, radius)
            if edge != -1:
                edge_masks[state] |= 1 << edge

        legal_count = board.cell_count() - board.move_count()

        return {
            "stone_counts": stone_counts,
            "edge_masks": edge_masks,
            "corner_masks": corner_masks,
            "legal_count": legal_count,
        }

    def _neighbor_stats_for_last_move(
        self,
        board,
        last_move: Optional[int],
        player: int,
    ) -> Tuple[int, int, int, int]:
        if last_move is None:
            return 0, 0, 0, 0

        coords = self._cell_coords(board)
        by_coord = self._coord_to_index(board)

        q, r = coords[last_move]

        same = 0
        opponent = 0
        empty = 0
        outside = 0

        for dq, dr in AXIAL_DIRECTIONS:
            n_index = by_coord.get((q + dq, r + dr))
            if n_index is None:
                outside += 1
                continue

            value = board.get_cell(n_index)
            if value == 0:
                empty += 1
            elif value == player:
                same += 1
            else:
                opponent += 1

        return same, opponent, empty, outside

    def _semantic_coverage_keys(
        self,
        board,
        board_size: int,
        last_move: Optional[int],
        last_player: int,
    ) -> Set[CoverageKey]:
        keys: Set[CoverageKey] = set()

        features = self._board_features(board, board_size)

        stone_counts = features["stone_counts"]
        edge_masks = features["edge_masks"]
        corner_masks = features["corner_masks"]
        legal_count = features["legal_count"]

        done = bool(board.is_done_game())
        winner = int(board.winner_player())
        win_kind = int(board.win_structure())
        move_count = int(board.move_count())
        current_player = -1 if done else int(board.current_player())

        white_count_b = self._bucket(stone_counts[1])
        black_count_b = self._bucket(stone_counts[2])
        move_count_b = self._bucket(move_count)
        legal_count_b = self._bucket(legal_count)

        keys.add(
            (
                "summary",
                board_size,
                move_count_b,
                current_player,
                int(done),
                winner,
                win_kind,
                white_count_b,
                black_count_b,
                legal_count_b,
                edge_masks[1],
                edge_masks[2],
                corner_masks[1],
                corner_masks[2],
            )
        )

        keys.add(("depth", board_size, move_count_b))
        keys.add(("turn", board_size, move_count_b, current_player))
        keys.add(("stones", board_size, 1, white_count_b))
        keys.add(("stones", board_size, 2, black_count_b))
        keys.add(("edge_mask", board_size, 1, edge_masks[1]))
        keys.add(("edge_mask", board_size, 2, edge_masks[2]))
        keys.add(("corner_mask", board_size, 1, corner_masks[1]))
        keys.add(("corner_mask", board_size, 2, corner_masks[2]))

        if last_move is not None:
            region, region_id = self._region_of_cell(board, board_size, last_move)

            same, opponent, empty, outside = self._neighbor_stats_for_last_move(
                board=board,
                last_move=last_move,
                player=last_player,
            )

            keys.add(("cell_played", board_size, last_player, last_move))
            keys.add(("region", board_size, last_player, region, region_id))
            keys.add(
                (
                    "local_context",
                    board_size,
                    last_player,
                    region,
                    self._bucket(same),
                    self._bucket(opponent),
                    self._bucket(empty),
                    self._bucket(outside),
                )
            )

        if done:
            keys.add(("terminal", board_size, winner, win_kind, move_count_b))

            if winner != 0:
                keys.add(
                    (
                        "win",
                        board_size,
                        winner,
                        STRUCTURE_NAMES.get(win_kind, "unknown"),
                        move_count_b,
                    )
                )

        return keys

    def _gui_snapshot(self, app) -> Dict[str, Any]:
        board = app.game

        if board is None:
            return {
                "has_game": False,
                "board_size": getattr(app, "board_size", None),
                "move_count": -1,
                "done": False,
                "winner": 0,
                "win_kind": 0,
                "cell_count": 0,
                "occupied_count": 0,
                "board_signature": (),
                "canvas_cells": -1,
                "canvas_stones": -1,
                "status": "",
                "board_label": "",
            }

        board_signature = tuple(int(board.get_cell(i)) for i in range(board.cell_count()))
        occupied_count = sum(1 for value in board_signature if value in (1, 2))

        try:
            canvas_cells = len(app.canvas.find_withtag("cell"))
        except Exception:
            canvas_cells = -1

        try:
            canvas_stones = len(app.canvas.find_withtag("stone"))
        except Exception:
            canvas_stones = -1

        try:
            status = str(app.status_var.get())
        except Exception:
            status = "<status-error>"

        try:
            board_label = str(app.board_label_var.get())
        except Exception:
            board_label = "<board-label-error>"

        return {
            "has_game": True,
            "board_size": int(app.board_size),
            "move_count": int(board.move_count()),
            "done": bool(board.is_done_game()),
            "winner": int(board.winner_player()),
            "win_kind": int(board.win_structure()),
            "cell_count": int(board.cell_count()),
            "occupied_count": occupied_count,
            "board_signature": board_signature,
            "canvas_cells": canvas_cells,
            "canvas_stones": canvas_stones,
            "status": status,
            "board_label": board_label,
        }

    def _gui_coverage_keys(
        self,
        app,
        board_size: int,
        last_event: str,
        valid_clicks: int,
        occupied_clicks: int,
        redraws: int,
        status_updates: int,
        resets: int,
    ) -> Set[CoverageKey]:
        keys: Set[CoverageKey] = set()
        snap = self._gui_snapshot(app)

        status = snap["status"]

        if "Turno" in status:
            status_kind = "turn"
        elif "Vittoria" in status or "vince" in status:
            status_kind = "win"
        elif "Patta" in status or "patta" in status:
            status_kind = "draw"
        elif "occupata" in status or "non valida" in status:
            status_kind = "invalid_move"
        elif "terminata" in status:
            status_kind = "done"
        else:
            status_kind = "other"

        keys.add(("gui_event", last_event))
        keys.add(("gui_status_kind", status_kind))
        keys.add(("gui_board_label", snap["board_label"]))
        keys.add(("gui_canvas_cells_bucket", self._bucket(int(snap["canvas_cells"]))))
        keys.add(("gui_canvas_stones_bucket", self._bucket(int(snap["canvas_stones"]))))
        keys.add(("gui_valid_clicks_bucket", self._bucket(valid_clicks)))
        keys.add(("gui_occupied_clicks_bucket", self._bucket(occupied_clicks)))
        keys.add(("gui_redraws_bucket", self._bucket(redraws)))
        keys.add(("gui_status_updates_bucket", self._bucket(status_updates)))
        keys.add(("gui_resets_bucket", self._bucket(resets)))
        keys.add(("gui_board_size", board_size))

        return keys

    def _check_gui_invariants(
        self,
        event: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
    ) -> Tuple[Optional[str], str]:
        if not after["has_game"]:
            return "BUG_GUI_00_MISSING_GAME", "la GUI non ha un game valido"

        expected_label = f"Board: {after['board_size']}"

        if event == "reset_board" and after["canvas_cells"] != after["cell_count"]:
            return (
                "BUG_GUI_01_CANVAS_NOT_CLEARED_AFTER_RESET",
                f"canvas_cells={after['canvas_cells']} ma cell_count={after['cell_count']}",
            )

        if event in ("click_valid", "click_after_done", "redraw") and after["canvas_stones"] != after["occupied_count"]:
            if before.get("done") and event in ("click_valid", "click_after_done"):
                return (
                    "BUG_GUI_04_CLICK_AFTER_DONE_DRAWS_FAKE_STONE",
                    f"canvas_stones={after['canvas_stones']} ma occupied_count={after['occupied_count']}",
                )
            return (
                "BUG_GUI_02_STONE_COUNT_MISMATCH_AFTER_REDRAW",
                f"canvas_stones={after['canvas_stones']} ma occupied_count={after['occupied_count']}",
            )

        if after["board_label"] != expected_label:
            return (
                "BUG_GUI_03_BOARD_LABEL_STALE",
                f"board_label={after['board_label']!r}, attesa={expected_label!r}",
            )

        if event == "reset_board":
            if after["move_count"] != 0 or after["occupied_count"] != 0 or after["done"]:
                return (
                    "BUG_GUI_07_RESET_STATE_NOT_CLEAN",
                    "dopo reset la board non è pulita",
                )

        if event == "click_occupied" and before.get("occupied_count", 0) > 0:
            if before["board_signature"] != after["board_signature"] or before["move_count"] != after["move_count"]:
                return (
                    "BUG_GUI_05_INVALID_CLICK_CHANGED_STATE",
                    "click invalido ha modificato il modello",
                )

            if not before.get("done"):
                status = after["status"].lower()
                if "occupata" not in status and "non valida" not in status:
                    return (
                        "BUG_GUI_06_INVALID_CLICK_STATUS_MISSING",
                        f"status dopo click occupato non segnala errore: {after['status']!r}",
                    )

        if before.get("done") and event in ("click_valid", "click_after_done"):
            if before["board_signature"] != after["board_signature"] or before["move_count"] != after["move_count"]:
                return (
                    "BUG_GUI_08_CLICK_AFTER_DONE_CHANGED_MODEL",
                    "click dopo fine partita ha modificato il modello",
                )

        status = after["status"]
        status_lower = status.lower()

        if after["done"]:
            if after["winner"] == 0:
                if "patta" not in status_lower and "conclusa" not in status_lower:
                    return (
                        "BUG_GUI_09_TERMINAL_STATUS_INCONSISTENT",
                        f"status terminale di patta incoerente: {status!r}",
                    )
            else:
                if "vince" not in status_lower and "vittoria" not in status_lower:
                    return (
                        "BUG_GUI_09_TERMINAL_STATUS_INCONSISTENT",
                        f"status terminale di vittoria incoerente: {status!r}",
                    )
        else:
            if "turno" not in status_lower and "occupata" not in status_lower and "non valida" not in status_lower:
                return (
                    "BUG_GUI_10_NONTERMINAL_STATUS_INCONSISTENT",
                    f"status non terminale incoerente: {status!r}",
                )

        return None, ""

    def _model_fingerprint(self, board) -> Dict[str, Any]:
        cell_count = board.cell_count()
        return {
            "cells": tuple(int(board.get_cell(i)) for i in range(cell_count)),
            "move_count": int(board.move_count()),
            "done": bool(board.is_done_game()),
            "winner": int(board.winner_player()),
            "win_kind": int(board.win_structure()),
        }

    def _check_model_invariants(
        self,
        board,
        *,
        event: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], str]:
        if board is None:
            return "BUG_MODEL_00_MISSING_BOARD", "board is None"

        cell_count = board.cell_count()
        occupied = 0

        for index in range(cell_count):
            value = int(board.get_cell(index))

            if value not in (0, 1, 2):
                return (
                    "BUG_MODEL_01_INVALID_CELL_VALUE",
                    f"cella {index} ha valore {value}",
                )
            if value != 0:
                occupied += 1

        move_count = int(board.move_count())

        if move_count != occupied:
            return (
                "BUG_MODEL_02_MOVE_COUNT_MISMATCH",
                f"move_count={move_count}, occupied={occupied}",
            )

        if move_count > cell_count:
            return (
                "BUG_MODEL_03_MOVE_COUNT_EXCEEDS_CELLS",
                f"move_count={move_count}, cell_count={cell_count}",
            )

        done = bool(board.is_done_game())
        winner = int(board.winner_player())
        win_kind = int(board.win_structure())

        if not done:
            if winner != 0:
                return (
                    "BUG_MODEL_04_WINNER_WHILE_OPEN",
                    f"winner={winner} ma la partita è aperta",
                )

            if win_kind != 0:
                return (
                    "BUG_MODEL_05_WIN_KIND_WHILE_OPEN",
                    f"win_kind={win_kind} ma la partita è aperta",
                )

            current_player = int(board.current_player())
            if current_player not in (1, 2):
                return (
                    "BUG_MODEL_06_INVALID_CURRENT_PLAYER",
                    f"current_player={current_player}",
                )
        else:
            if winner not in (0, 1, 2):
                return (
                    "BUG_MODEL_07_INVALID_WINNER",
                    f"winner={winner}",
                )

            if winner != 0 and win_kind not in (1, 2, 3):
                return (
                    "BUG_MODEL_08_WINNER_WITHOUT_STRUCTURE",
                    f"winner={winner}, win_kind={win_kind}",
                )

            if winner == 0 and win_kind != 0:
                return (
                    "BUG_MODEL_09_DRAW_WITH_WIN_KIND",
                    f"winner=0 ma win_kind={win_kind}",
                )

        if before is not None and event is not None:
            after = self._model_fingerprint(board)
            model_keys = ("cells", "move_count", "done", "winner", "win_kind")

            if event == "click_valid" and not before["done"]:
                if after["move_count"] != before["move_count"] + 1:
                    return (
                        "BUG_MODEL_10_VALID_MOVE_MOVE_COUNT",
                        f"move_count {before['move_count']} -> {after['move_count']}",
                    )

                changed = [
                    index
                    for index, (old, new) in enumerate(zip(before["cells"], after["cells"]))
                    if old != new
                ]

                if len(changed) != 1:
                    return (
                        "BUG_MODEL_11_VALID_MOVE_CELL_DELTA",
                        f"celle modificate={len(changed)}",
                    )

                index = changed[0]
                if before["cells"][index] != 0 or after["cells"][index] == 0:
                    return (
                        "BUG_MODEL_11_VALID_MOVE_CELL_DELTA",
                        f"cella {index} non è passata da vuota a occupata",
                    )

            elif event in ("click_occupied", "click_after_done", "redraw", "status_update"):
                if any(before[key] != after[key] for key in model_keys):
                    return (
                        "BUG_MODEL_12_NOOP_EVENT_CHANGED_MODEL",
                        f"evento {event} ha modificato lo stato del modello",
                    )

            elif event == "reset_board":
                if after["move_count"] != 0 or any(cell != 0 for cell in after["cells"]):
                    return (
                        "BUG_MODEL_13_RESET_NOT_CLEAN",
                        "reset non ha prodotto una board vuota",
                    )

        return None, ""

    # ============================================================
    # GENERATION AND MUTATION
    # ============================================================

    def _generate_random_raw_sequence(self) -> Tuple[int, List[int]]:
        board_size = self.rng.choice(self.board_sizes)
        length = self.rng.randint(1, self.max_len)
        moves = [self._random_raw_move() for _ in range(length)]
        return board_size, moves

    def _generate_valid_random_sequence(self) -> Tuple[int, List[int]]:
        board_size = self.rng.choice(self.board_sizes)
        length = self.rng.randint(1, self.max_len)
        moves = [self._random_raw_move() for _ in range(length)]
        return board_size, moves

    def _choose_entry_coverage_guided(self) -> CorpusEntry:
        weights: List[float] = []

        for entry in self.corpus:
            weight = 1.0 + float(entry.gain)
            weight = weight / math.sqrt(1.0 + float(entry.executions))
            weights.append(max(weight, 0.01))

        return self.rng.choices(self.corpus, weights=weights, k=1)[0]

    def _uses_corpus_scheduling(self) -> bool:
        return self.mode in (
            "coverage_guided",
            "coverage_guided_rate",
            "rgr_positive",
            "rgr_positive_rate",
            "anti_rgr_negative",
            "anti_rgr_negative_rate",
        )

    def _generate_coverage_guided_sequence(self) -> Tuple[CorpusEntry, int, List[int]]:
        entry = self._choose_entry_coverage_guided()
        entry.executions += 1
        board_size, moves = self._mutate(entry)
        return entry, board_size, moves

    def _choose_entry_rate(self) -> CorpusEntry:
        weights: List[float] = []

        for entry in self.corpus:
            reward = float(entry.coverage_found) + 5.0 * float(entry.bugs_found)
            time_cost = max(entry.total_time, 0.001)
            rate = reward / time_cost
            exploitation_penalty = math.sqrt(1.0 + float(entry.executions))
            weight = 1.0 + (rate / exploitation_penalty)
            weights.append(max(weight, 0.01))

        return self.rng.choices(self.corpus, weights=weights, k=1)[0]

    def _choose_entry_rgr_positive(self, *, time_normalized: bool) -> CorpusEntry:
        weights: List[float] = []

        for entry in self.corpus:
            bug_reward = float(entry.bugs_found)
            coverage_reward = 0.10 * float(entry.coverage_found)
            reward = bug_reward + coverage_reward

            if time_normalized:
                reward = reward / max(entry.total_time, 0.001)

            exploitation_penalty = math.sqrt(1.0 + float(entry.executions))
            weight = 1.0 + (reward / exploitation_penalty)
            weights.append(max(weight, 0.01))

        return self.rng.choices(self.corpus, weights=weights, k=1)[0]

    def _choose_entry_anti_rgr_negative(self, *, time_normalized: bool) -> CorpusEntry:
        weights: List[float] = []
        beta = 5.0

        for entry in self.corpus:
            exploration_reward = 1.0 + float(entry.coverage_found)
            bug_penalty = 1.0 + beta * float(entry.bugs_found)
            reward = exploration_reward / bug_penalty

            if time_normalized:
                reward = reward / max(entry.total_time, 0.001)

            exploitation_penalty = math.sqrt(1.0 + float(entry.executions))
            weight = 1.0 + (reward / exploitation_penalty)
            weights.append(max(weight, 0.01))

        return self.rng.choices(self.corpus, weights=weights, k=1)[0]

    def _generate_rate_sequence(self) -> Tuple[CorpusEntry, int, List[int]]:
        entry = self._choose_entry_rate() 
        entry.executions += 1
        board_size, moves = self._mutate(entry)
        return entry, board_size, moves

    def _generate_rgr_positive_sequence(self, *, time_normalized: bool) -> Tuple[CorpusEntry, int, List[int]]:
        entry = self._choose_entry_rgr_positive(time_normalized=time_normalized)
        entry.executions += 1
        board_size, moves = self._mutate(entry)
        return entry, board_size, moves

    def _generate_anti_rgr_negative_sequence(self, *, time_normalized: bool) -> Tuple[CorpusEntry, int, List[int]]:
        entry = self._choose_entry_anti_rgr_negative(time_normalized=time_normalized)
        entry.executions += 1
        board_size, moves = self._mutate(entry)
        return entry, board_size, moves

    def _random_raw_move(self) -> int:
        return self.rng.randint(0, 10_000_000)

    def _random_raw_block(self, min_len: int = 2, max_len: int = 12) -> List[int]:
        length = self.rng.randint(min_len, max_len)
        return [self._random_raw_move() for _ in range(length)]

    def _mutate_once(self, moves: List[int]) -> List[int]:
        mutated = list(moves)

        if not mutated:
            mutated.extend(self._random_raw_block(1, min(8, self.max_len)))
            return mutated

        op = self.rng.random()

        if op < 0.25 and len(mutated) < self.max_len:
            pos = self.rng.randint(0, len(mutated))
            mutated.insert(pos, self._random_raw_move())

        elif op < 0.40 and len(mutated) < self.max_len:
            pos = self.rng.randint(0, len(mutated))
            space_left = self.max_len - len(mutated)
            block = self._random_raw_block(2, min(12, max(2, space_left)))
            mutated[pos:pos] = block[:space_left]

        elif op < 0.70:
            pos = self.rng.randrange(len(mutated))
            mutated[pos] = self._random_raw_move()

        elif op < 0.88 and len(mutated) > 1:
            pos = self.rng.randrange(len(mutated))
            del mutated[pos]

        else:
            pos = self.rng.randrange(len(mutated))
            delta = self.rng.choice([-97, -31, -7, -1, 1, 7, 31, 97])
            mutated[pos] = max(0, mutated[pos] + delta)

        if len(mutated) > self.max_len:
            mutated = mutated[: self.max_len]

        return mutated

    def _mutate(self, entry: CorpusEntry) -> Tuple[int, List[int]]:
        board_size = entry.board_size

        if self.rng.random() < 0.08:
            board_size = self.rng.choice(self.board_sizes)

        moves = list(entry.moves)

        rounds = max(1, self.mutation_rounds)
        extra_rounds = 0

        if self.rng.random() < 0.20:
            extra_rounds += 1
        if self.rng.random() < 0.05:
            extra_rounds += 2

        for _ in range(rounds + extra_rounds):
            moves = self._mutate_once(moves)

        return board_size, moves

    # ============================================================
    # MODEL EXECUTOR
    # ============================================================

    def _run_model_sequence(self, board_size: int, raw_moves: List[int]) -> RunResult:
        started = time.time()
        initial_board_size = board_size
        session, board = self._new_session(board_size)

        coverage: Set[CoverageKey] = set()
        actual_moves: List[int] = []
        bug_id: Optional[str] = None
        bug_message = ""
        last_action = "start_session"

        coverage.update(
            self._semantic_coverage_keys(
                board=board,
                board_size=board_size,
                last_move=None,
                last_player=0,
            )
        )

        if self.enable_model_invariants:
            model_bug, model_message = self._check_model_invariants(board)
            if model_bug is not None:
                bug_id = model_bug
                bug_message = model_message

        for raw in raw_moves:
            if bug_id is not None:
                break

            if board.is_done_game():
                break

            valid = self._valid_moves(board)
            if not valid:
                break

            raw_abs = abs(int(raw))
            chosen_index = valid[raw_abs % len(valid)]
            move_arg = self._bounded("BIntT0T169T", chosen_index)

            if not session.can_play_move(move_arg):
                break

            player_before = int(board.current_player())
            session.play_move(move_arg)
            actual_moves.append(chosen_index)
            last_action = f"play_move:{chosen_index}"

            coverage.update(
                self._semantic_coverage_keys(
                    board=board,
                    board_size=board_size,
                    last_move=chosen_index,
                    last_player=player_before,
                )
            )

            if self.enable_model_invariants:
                model_bug, model_message = self._check_model_invariants(board)
                if model_bug is not None:
                    bug_id = model_bug
                    bug_message = model_message
                    break

        elapsed = time.time() - started

        return RunResult(
            target="model",
            initial_board_size=initial_board_size,
            board_size=board_size,
            raw_moves=list(raw_moves),
            actual_moves=actual_moves,
            coverage=coverage,
            steps_executed=len(actual_moves),
            done=bool(board.is_done_game()),
            winner=int(board.winner_player()),
            win_kind=int(board.win_structure()),
            move_count=int(board.move_count()),
            elapsed_seconds=elapsed,
            bug_id=bug_id,
            base_bug_id=bug_id,
            bug_message=bug_message,
            last_action=last_action,
            last_event=last_action.split(":", 1)[0],
        )

    # ============================================================
    # GUI EXECUTOR
    # ============================================================

    def _choose_gui_event(self, raw: int) -> str:
        if self.mode == "valid_random":
            return "click_valid"

        code = abs(int(raw)) % 100

        if code < 65:
            return "click_valid"
        if code < 78:
            return "click_occupied"
        if code < 87:
            return "redraw"
        if code < 95:
            return "status_update"
        return "reset_board"

    def _pick_next_board_size(self, raw: int, current_board_size: int) -> int:
        if not self.board_sizes:
            return current_board_size
        index = (abs(int(raw)) // 100) % len(self.board_sizes)
        return self.board_sizes[index]

    def _run_gui_sequence(self, board_size: int, raw_moves: List[int]) -> RunResult:
        if self.gui_app is None:
            raise RuntimeError("Target GUI richiesto ma gui_app non inizializzata")

        started = time.time()
        initial_board_size = board_size
        app = self.gui_app

        coverage: Set[CoverageKey] = set()
        actual_moves: List[int] = []
        bug_id: Optional[str] = None
        bug_message = ""

        gui_events_executed = 0
        gui_valid_clicks = 0
        gui_occupied_clicks = 0
        gui_redraws = 0
        gui_status_updates = 0
        gui_resets = 0

        last_event = "start_session"
        last_action = "start_session"
        last_move: Optional[int] = None
        last_player = 0

        app.fuzz_reset_to_size(board_size)
        board = app.game

        coverage.update(
            self._semantic_coverage_keys(
                board=board,
                board_size=board_size,
                last_move=None,
                last_player=0,
            )
        )

        coverage.update(
            self._gui_coverage_keys(
                app=app,
                board_size=board_size,
                last_event=last_event,
                valid_clicks=gui_valid_clicks,
                occupied_clicks=gui_occupied_clicks,
                redraws=gui_redraws,
                status_updates=gui_status_updates,
                resets=gui_resets,
            )
        )

        
        initial_snapshot = self._gui_snapshot(app)
        initial_bug, initial_message = self._check_gui_invariants(
            event="start_session",
            before=initial_snapshot,
            after=initial_snapshot,
        )
        if initial_bug is not None:
            bug_id = initial_bug
            bug_message = initial_message

        if bug_id is None and self.enable_model_invariants and board is not None:
            model_bug, model_message = self._check_model_invariants(board)
            if model_bug is not None:
                bug_id = model_bug
                bug_message = model_message

        if bug_id is None:
            for raw in raw_moves:
                board = app.game
                if board is None:
                    break

                event = self._choose_gui_event(raw)
                before = self._gui_snapshot(app)

                event_for_oracle = event
                if event == "click_valid" and before["done"]:
                    event_for_oracle = "click_after_done"

                before_model = (
                    self._model_fingerprint(board)
                    if self.enable_model_invariants
                    else None
                )

                last_event = event_for_oracle
                gui_events_executed += 1

                try:
                    if event == "reset_board":
                        new_size = self._pick_next_board_size(raw, board_size)
                        app.fuzz_reset_to_size(new_size)
                        board_size = new_size
                        board = app.game
                        gui_resets += 1
                        last_move = None
                        last_player = 0
                        last_action = f"reset_board:{new_size}"

                    elif event == "redraw":
                        app._redraw_stones()
                        try:
                            app.root.update_idletasks()
                        except Exception:
                            pass
                        gui_redraws += 1
                        last_action = "redraw"

                    elif event == "status_update":
                        app._refresh_status("Fuzz status update")
                        try:
                            app.root.update_idletasks()
                        except Exception:
                            pass
                        gui_status_updates += 1
                        last_action = "status_update"

                    elif event == "click_occupied":
                        occupied = self._occupied_moves(board)
                        if occupied:
                            index = occupied[(abs(int(raw)) // 100) % len(occupied)]
                            app.fuzz_click_cell(index)
                            gui_occupied_clicks += 1
                            last_action = f"click_occupied:{index}"
                        else:
                            app._refresh_status("Fuzz occupied click skipped")
                            try:
                                app.root.update_idletasks()
                            except Exception:
                                pass
                            gui_status_updates += 1
                            last_action = "click_occupied:skipped"

                    elif event == "click_valid":
                        if before["done"]:
                            all_cells = list(range(board.cell_count()))
                            index = all_cells[(abs(int(raw)) // 100) % len(all_cells)]
                            app.fuzz_click_cell(index)
                            gui_valid_clicks += 1
                            last_action = f"click_after_done:{index}"
                        else:
                            valid = self._valid_moves(board)
                            if not valid:
                                break

                            index = valid[(abs(int(raw)) // 100) % len(valid)]
                            player_before = int(board.current_player())
                            app.fuzz_click_cell(index)
                            actual_moves.append(index)
                            gui_valid_clicks += 1
                            last_move = index
                            last_player = player_before
                            last_action = f"click_valid:{index}"

                    else:
                        raise ValueError(f"Evento GUI sconosciuto: {event}")

                except Exception as exc:
                    bug_id = "BUG_GUI_99_UNHANDLED_EXCEPTION"
                    bug_message = repr(exc)
                    break

                board = app.game
                after = self._gui_snapshot(app)

                coverage.update(
                    self._semantic_coverage_keys(
                        board=board,
                        board_size=board_size,
                        last_move=last_move,
                        last_player=last_player,
                    )
                )
                coverage.update(
                    self._gui_coverage_keys(
                        app=app,
                        board_size=board_size,
                        last_event=last_event,
                        valid_clicks=gui_valid_clicks,
                        occupied_clicks=gui_occupied_clicks,
                        redraws=gui_redraws,
                        status_updates=gui_status_updates,
                        resets=gui_resets,
                    )
                )

                found_bug, message = self._check_gui_invariants(
                    event=event_for_oracle,
                    before=before,
                    after=after,
                )
                if found_bug is not None:
                    bug_id = found_bug
                    bug_message = message
                    break

                if self.enable_model_invariants and board is not None:
                    model_bug, model_message = self._check_model_invariants(
                        board,
                        event=event_for_oracle,
                        before=before_model,
                    )
                    if model_bug is not None:
                        bug_id = model_bug
                        bug_message = model_message
                        break

        board = app.game
        elapsed = time.time() - started

        return RunResult(
            target="gui",
            initial_board_size=initial_board_size,
            board_size=board_size,
            raw_moves=list(raw_moves),
            actual_moves=actual_moves,
            coverage=coverage,
            steps_executed=gui_events_executed,
            done=bool(board.is_done_game()),
            winner=int(board.winner_player()),
            win_kind=int(board.win_structure()),
            move_count=int(board.move_count()),
            elapsed_seconds=elapsed,
            bug_id=bug_id,
            base_bug_id=bug_id,
            bug_message=bug_message,
            last_action=last_action,
            last_event=last_event,
            gui_events_executed=gui_events_executed,
            gui_valid_clicks=gui_valid_clicks,
            gui_occupied_clicks=gui_occupied_clicks,
            gui_redraws=gui_redraws,
            gui_status_updates=gui_status_updates,
            gui_resets=gui_resets,
        )

    # ============================================================
    # MAIN LOOP
    # ============================================================

    def _time_budget_expired(self) -> bool:
        if self.time_budget_seconds is None:
            return False
        return (time.time() - self.start_time) >= self.time_budget_seconds

    def _run_sequence(self, board_size: int, raw_moves: List[int]) -> RunResult:
        if self.target == "model":
            return self._run_model_sequence(board_size, raw_moves)
        if self.target == "gui":
            return self._run_gui_sequence(board_size, raw_moves)
        raise ValueError(f"Target sconosciuto: {self.target}")

    def _stable_variant_index(self, source: str) -> int:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return int(digest[:16], 16) % self.bug_variant_mod

    def _bug_variant_source(self, base_bug_id: str, result: RunResult) -> str:
        raw_tail = ",".join(str(value) for value in result.raw_moves[-5:])
        actual_tail = ",".join(str(value) for value in result.actual_moves[-5:])
        parts = [
            base_bug_id,
            f"last_event={result.last_event}",
            f"last_action={result.last_action}",
            f"move_count={result.move_count}",
            f"initial_board={result.initial_board_size}",
            f"final_board={result.board_size}",
            f"steps={result.steps_executed}",
            f"raw_len={len(result.raw_moves)}",
            f"actual_len={len(result.actual_moves)}",
            f"done={int(result.done)}",
            f"winner={result.winner}",
            f"win_kind={result.win_kind}",
            f"gui_valid={result.gui_valid_clicks}",
            f"gui_occupied={result.gui_occupied_clicks}",
            f"gui_redraws={result.gui_redraws}",
            f"gui_status={result.gui_status_updates}",
            f"gui_resets={result.gui_resets}",
            f"raw_tail={raw_tail}",
            f"actual_tail={actual_tail}",
        ]
        return "|".join(parts)

    def _attach_synthetic_bug_identity(self, result: RunResult) -> None:
        if result.bug_id is None:
            return

        base_bug_id = result.base_bug_id or result.bug_id
        result.base_bug_id = base_bug_id

        if self.bug_variant_mod <= 1:
            result.bug_id = base_bug_id
            result.bug_variant_source = base_bug_id
            return

        source = self._bug_variant_source(base_bug_id, result)
        variant = self._stable_variant_index(source)
        result.bug_id = f"{base_bug_id}::v{variant}"
        result.bug_variant_source = source

    def fuzz(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.start_time = time.time()
        self._open_timeline()

        print("UI/action fuzz engine avviato")
        print(f"Target: {self.target}")
        print(f"Mode: {self.mode}")
        print(f"Run id: {self.run_id}")
        print(f"Seed: {self.seed}")
        print(f"Max iterations: {self.iterations}")
        print(f"Time budget seconds: {self.time_budget_seconds}")
        print(f"Board sizes: {self.board_sizes}")
        print(f"Max sequence length: {self.max_len}")
        print(f"Bug variant mod: {self.bug_variant_mod}")
        print(f"Injected bugs in target: {self.enable_injected_bugs}")
        print(f"GUI file: {self.gui_file}")
        print(f"Output dir: {self.out_dir}")
        print()

        iteration = 0

        try:
            while iteration < self.iterations and not self._time_budget_expired():
                iteration += 1
                parent_entry: Optional[CorpusEntry] = None

                if self.mode == "random_raw":
                    board_size, candidate_moves = self._generate_random_raw_sequence()

                elif self.mode == "valid_random":
                    board_size, candidate_moves = self._generate_valid_random_sequence()

                elif self.mode == "coverage_guided":
                    parent_entry, board_size, candidate_moves = self._generate_coverage_guided_sequence()

                elif self.mode == "coverage_guided_rate":
                    parent_entry, board_size, candidate_moves = self._generate_rate_sequence()

                elif self.mode == "rgr_positive":
                    parent_entry, board_size, candidate_moves = self._generate_rgr_positive_sequence(
                        time_normalized=False
                    )

                elif self.mode == "rgr_positive_rate":
                    parent_entry, board_size, candidate_moves = self._generate_rgr_positive_sequence(
                        time_normalized=True
                    )

                elif self.mode == "anti_rgr_negative":
                    parent_entry, board_size, candidate_moves = self._generate_anti_rgr_negative_sequence(
                        time_normalized=False
                    )

                elif self.mode == "anti_rgr_negative_rate":
                    parent_entry, board_size, candidate_moves = self._generate_anti_rgr_negative_sequence(
                        time_normalized=True
                    )

                else:
                    raise ValueError(f"Modalità non gestita: {self.mode}")

                try:
                    result = self._run_sequence(board_size, candidate_moves)
                except Exception as exc:
                    self.stats["exceptions"] += 1
                    self._save_exception(iteration, board_size, candidate_moves, exc)
                    self._write_timeline_row(iteration, None, 0)
                    continue

                self._attach_synthetic_bug_identity(result)

                new_keys = result.coverage - self.global_coverage
                new_count = len(new_keys)

                new_bug = False
                if result.bug_id is not None:
                    if result.base_bug_id is not None:
                        self.base_bugs_found.add(result.base_bug_id)
                    if result.bug_id not in self.bugs_found:
                        self.bugs_found.add(result.bug_id)
                        new_bug = True
                    self.stats["bug_hits"] += 1
                    self.stats[f"bug_hit_{result.bug_id}"] += 1
                    if result.base_bug_id is not None:
                        self.stats[f"base_bug_hit_{result.base_bug_id}"] += 1

                if new_count > 0:
                    self.global_coverage.update(new_keys)

                if parent_entry is not None:
                    parent_entry.total_time += result.elapsed_seconds
                    parent_entry.coverage_found += new_count
                    if new_bug:
                        parent_entry.bugs_found += 1

                if self._uses_corpus_scheduling():
                    if new_count > 0 or new_bug:
                        self.corpus.append(
                            CorpusEntry(
                                board_size=board_size,
                                moves=candidate_moves,
                                gain=new_count,
                                executions=0,
                                created_at_iteration=iteration,
                                total_time=result.elapsed_seconds,
                                coverage_found=new_count,
                                bugs_found=1 if new_bug else 0,
                            )
                        )

                        self.best_gain = max(self.best_gain, new_count)
                        self.stats["interesting_inputs"] += 1

                self._record_result(result, new_count, new_bug)
                self._write_timeline_row(iteration, result, new_count)

                if iteration % self.report_every == 0 or iteration == 1:
                    self._print_report(iteration)

        finally:
            self.stats["completed_iterations"] = iteration
            self._close_timeline()
            self._destroy_gui_app()

        self._save_outputs()
        self._print_final_report()

    # ============================================================
    # OUTPUT
    # ============================================================

    def _record_result(self, result: RunResult, new_coverage_count: int, new_bug: bool):
        self.stats["runs"] += 1
        self.stats["executed_steps"] += result.steps_executed
        self.stats["total_new_coverage"] += new_coverage_count
        self.stats[f"board_size_{result.board_size}"] += 1
        self.stats[f"target_{result.target}"] += 1

        initial_board = result.initial_board_size
        final_board = result.board_size
        self.stats[f"board_initial_samples_{initial_board}"] += 1
        self.stats[f"board_initial_time_{initial_board}"] += result.elapsed_seconds
        self.stats[f"board_initial_new_coverage_{initial_board}"] += new_coverage_count
        self.stats[f"board_final_samples_{final_board}"] += 1

        if result.bug_id is not None:
            self.stats[f"board_initial_bug_hits_{initial_board}"] += 1
            self.stats[f"board_final_bug_hits_{final_board}"] += 1

        if new_bug:
            self.stats[f"board_initial_unique_bugs_{initial_board}"] += 1
            self.stats[f"board_final_unique_bugs_{final_board}"] += 1

        if result.target == "gui":
            self.stats["gui_events_executed"] += result.gui_events_executed
            self.stats["gui_valid_clicks"] += result.gui_valid_clicks
            self.stats["gui_occupied_clicks"] += result.gui_occupied_clicks
            self.stats["gui_redraws"] += result.gui_redraws
            self.stats["gui_status_updates"] += result.gui_status_updates
            self.stats["gui_resets"] += result.gui_resets

            self.stats[f"board_initial_gui_events_{initial_board}"] += result.gui_events_executed
            self.stats[f"board_initial_valid_clicks_{initial_board}"] += result.gui_valid_clicks
            self.stats[f"board_initial_occupied_clicks_{initial_board}"] += result.gui_occupied_clicks
            self.stats[f"board_initial_redraws_{initial_board}"] += result.gui_redraws
            self.stats[f"board_initial_status_updates_{initial_board}"] += result.gui_status_updates
            self.stats[f"board_initial_resets_{initial_board}"] += result.gui_resets

        if result.done:
            self.stats["terminal_games"] += 1

            if result.winner == 0:
                self.stats["draws"] += 1
            else:
                self.stats["wins"] += 1
                self.stats[f"winner_{result.winner}"] += 1
                self.stats[f"win_kind_{result.win_kind}"] += 1

        if new_bug:
            self.stats["unique_bugs_found"] += 1

    def _open_timeline(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.timeline_file = (self.out_dir / "timeline.csv").open("w", newline="", encoding="utf-8")
        self.timeline_writer = csv.DictWriter(
            self.timeline_file,
            fieldnames=[
                "run_id",
                "target",
                "mode",
                "seed",
                "iteration",
                "elapsed_seconds_total",
                "elapsed_seconds_case",
                "coverage_total",
                "new_coverage",
                "corpus_size",
                "initial_board_size",
                "board_size",
                "raw_len",
                "actual_len",
                "steps_executed",
                "done",
                "winner",
                "win_kind",
                "move_count",
                "bug_id",
                "base_bug_id",
                "bug_variant_source",
                "bug_message",
                "last_action",
                "last_event",
                "unique_bugs_total",
                "base_bugs_total",
                "exceptions_total",
                "gui_events_executed",
                "gui_valid_clicks",
                "gui_occupied_clicks",
                "gui_redraws",
                "gui_status_updates",
                "gui_resets",
            ],
        )
        self.timeline_writer.writeheader()

    def _close_timeline(self):
        if self.timeline_file is not None:
            self.timeline_file.close()
            self.timeline_file = None
            self.timeline_writer = None

    def _write_timeline_row(
        self,
        iteration: int,
        result: Optional[RunResult],
        new_coverage_count: int,
    ):
        if self.timeline_writer is None:
            return

        elapsed_total = time.time() - self.start_time

        self.timeline_writer.writerow(
            {
                "run_id": self.run_id,
                "target": self.target,
                "mode": self.mode,
                "seed": self.seed if self.seed is not None else "",
                "iteration": iteration,
                "elapsed_seconds_total": elapsed_total,
                "elapsed_seconds_case": result.elapsed_seconds if result else "",
                "coverage_total": len(self.global_coverage),
                "new_coverage": new_coverage_count,
                "corpus_size": len(self.corpus),
                "initial_board_size": result.initial_board_size if result else "",
                "board_size": result.board_size if result else "",
                "raw_len": len(result.raw_moves) if result else "",
                "actual_len": len(result.actual_moves) if result else "",
                "steps_executed": result.steps_executed if result else "",
                "done": int(result.done) if result else "",
                "winner": result.winner if result else "",
                "win_kind": result.win_kind if result else "",
                "move_count": result.move_count if result else "",
                "bug_id": result.bug_id if result and result.bug_id else "",
                "base_bug_id": result.base_bug_id if result and result.base_bug_id else "",
                "bug_variant_source": result.bug_variant_source if result else "",
                "bug_message": result.bug_message if result else "",
                "last_action": result.last_action if result else "",
                "last_event": result.last_event if result else "",
                "unique_bugs_total": len(self.bugs_found),
                "base_bugs_total": len(self.base_bugs_found),
                "exceptions_total": self.stats.get("exceptions", 0),
                "gui_events_executed": result.gui_events_executed if result else "",
                "gui_valid_clicks": result.gui_valid_clicks if result else "",
                "gui_occupied_clicks": result.gui_occupied_clicks if result else "",
                "gui_redraws": result.gui_redraws if result else "",
                "gui_status_updates": result.gui_status_updates if result else "",
                "gui_resets": result.gui_resets if result else "",
            }
        )

        if iteration % self.report_every == 0:
            try:
                self.timeline_file.flush()
            except Exception:
                pass

    def _print_report(self, iteration: int):
        elapsed = max(0.001, time.time() - self.start_time)
        runs_per_sec = iteration / elapsed

        print(
            f"[{iteration:>7}/{self.iterations}] "
            f"target={self.target:<5} "
            f"mode={self.mode:<20} "
            f"coverage={len(self.global_coverage):>6} "
            f"corpus={len(self.corpus):>5} "
            f"bugs={len(self.bugs_found):>2} "
            f"interesting={self.stats.get('interesting_inputs', 0):>5} "
            f"terminal={self.stats.get('terminal_games', 0):>5} "
            f"wins={self.stats.get('wins', 0):>5} "
            f"runs/s={runs_per_sec:.1f}"
        )

    def _print_final_report(self):
        elapsed = max(0.001, time.time() - self.start_time)
        runs = self.stats.get("runs", 0)
        samples_per_second = float(runs) / elapsed
        bugs_per_sample = float(len(self.bugs_found)) / max(1.0, float(runs))
        bugs_per_second = float(len(self.bugs_found)) / elapsed
        coverage_per_second = float(len(self.global_coverage)) / elapsed

        print()
        print("Fuzzing concluso")
        print(f"Target: {self.target}")
        print(f"Mode: {self.mode}")
        print(f"Run id: {self.run_id}")
        print(f"Tempo: {elapsed:.2f}s")
        print(f"Runs: {runs}")
        print(f"Coverage totale: {len(self.global_coverage)}")
        print(f"Corpus finale: {len(self.corpus)}")
        print(f"Input interessanti: {self.stats.get('interesting_inputs', 0)}")
        print(f"Bug unici sintetici trovati: {len(self.bugs_found)}")
        print(f"Bug base/oracle trovati: {len(self.base_bugs_found)}")
        print(f"Samples/sec: {samples_per_second:.3f}")
        print(f"Bugs/sample: {bugs_per_sample:.6f}")
        print(f"Bugs/sec: {bugs_per_second:.6f}")
        print(f"Coverage/sec: {coverage_per_second:.3f}")
        print(f"Partite terminali: {self.stats.get('terminal_games', 0)}")
        print(f"Vittorie: {self.stats.get('wins', 0)}")
        print(f"Eccezioni: {self.stats.get('exceptions', 0)}")

        if self.target == "gui":
            print()
            print("Eventi GUI:")
            print(f"  valid clicks: {self.stats.get('gui_valid_clicks', 0)}")
            print(f"  occupied clicks: {self.stats.get('gui_occupied_clicks', 0)}")
            print(f"  redraws: {self.stats.get('gui_redraws', 0)}")
            print(f"  status updates: {self.stats.get('gui_status_updates', 0)}")
            print(f"  resets: {self.stats.get('gui_resets', 0)}")

        if self.bugs_found:
            print()
            print("Bug unici:")
            for bug_id in sorted(self.bugs_found):
                hits = self.stats.get(f"bug_hit_{bug_id}", 0)
                print(f"  {bug_id}: {hits} hit totali")

        if self.stats.get("wins", 0) > 0:
            print()
            print("Vittorie per struttura:")
            for win_kind in (1, 2, 3):
                count = self.stats.get(f"win_kind_{win_kind}", 0)
                print(f"  {STRUCTURE_NAMES[win_kind]}: {count}")

        print()
        print(f"Output salvato in: {self.out_dir}")

    def _save_exception(
        self,
        iteration: int,
        board_size: int,
        moves: List[int],
        exc: Exception,
    ):
        failures_dir = self.out_dir / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "iteration": iteration,
            "target": self.target,
            "mode": self.mode,
            "board_size": board_size,
            "moves": moves,
            "exception": repr(exc),
            "traceback": traceback.format_exc(),
        }

        path = failures_dir / f"failure_{iteration}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _save_outputs(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        elapsed_seconds = max(0.001, time.time() - self.start_time)
        runs = self.stats.get("runs", 0)

        corpus_payload = [
            {
                "board_size": entry.board_size,
                "moves": entry.moves,
                "gain": entry.gain,
                "executions": entry.executions,
                "created_at_iteration": entry.created_at_iteration,
                "total_time": entry.total_time,
                "coverage_found": entry.coverage_found,
                "bugs_found": entry.bugs_found,
            }
            for entry in self.corpus
        ]

        stats_payload = dict(self.stats)
        stats_payload.update(
            {
                "target": self.target,
                "mode": self.mode,
                "run_id": self.run_id,
                "seed": self.seed,
                "requested_iterations": self.iterations,
                "completed_iterations": self.stats.get("completed_iterations", self.stats.get("runs", 0)),
                "time_budget_seconds": self.time_budget_seconds,
                "coverage_total": len(self.global_coverage),
                "corpus_size": len(self.corpus),
                "unique_bugs_total": len(self.bugs_found),
                "max_len": self.max_len,
                "board_sizes": self.board_sizes,
                "mutation_rounds": self.mutation_rounds,
                "initial_corpus_seed_lengths": [0, 5, 10, 20, 40],
                "deep_corpus_seeds_enabled": True,
                "block_mutation_enabled": True,
                "enable_injected_bugs": self.enable_injected_bugs,
                "gui_file": str(self.gui_file) if self.gui_file else None,
                "bug_variant_mod": self.bug_variant_mod,
                "base_bugs_total": len(self.base_bugs_found),
                "elapsed_seconds": elapsed_seconds,
                "samples_per_second": float(runs) / elapsed_seconds,
                "bugs_per_sample": float(len(self.bugs_found)) / max(1.0, float(runs)),
                "bugs_per_second": float(len(self.bugs_found)) / elapsed_seconds,
                "coverage_per_second": float(len(self.global_coverage)) / elapsed_seconds,
                "bug_hits_total": self.stats.get("bug_hits", 0),
                "bug_hits_per_sample": float(self.stats.get("bug_hits", 0)) / max(1.0, float(runs)),
                "bug_hits_per_second": float(self.stats.get("bug_hits", 0)) / elapsed_seconds,
                "board_metrics": self._board_metrics_payload(),
            }
        )

        top_corpus = sorted(
            self.corpus,
            key=lambda e: (e.gain, e.coverage_found + 5 * e.bugs_found, -len(e.moves)),
            reverse=True,
        )[:50]

        top_payload = [
            {
                "board_size": entry.board_size,
                "moves": entry.moves,
                "gain": entry.gain,
                "executions": entry.executions,
                "created_at_iteration": entry.created_at_iteration,
                "total_time": entry.total_time,
                "coverage_found": entry.coverage_found,
                "bugs_found": entry.bugs_found,
            }
            for entry in top_corpus
        ]

        coverage_payload = sorted(
            [list(key) for key in self.global_coverage],
            key=lambda item: repr(item),
        )

        bugs_payload = {
            "unique_bugs": sorted(self.bugs_found),
            "base_bugs": sorted(self.base_bugs_found),
            "hit_counts": {
                bug_id: self.stats.get(f"bug_hit_{bug_id}", 0)
                for bug_id in sorted(self.bugs_found)
            },
            "base_hit_counts": {
                bug_id: self.stats.get(f"base_bug_hit_{bug_id}", 0)
                for bug_id in sorted(self.base_bugs_found)
            },
        }

        (self.out_dir / "corpus.json").write_text(
            json.dumps(corpus_payload, indent=2),
            encoding="utf-8",
        )

        (self.out_dir / "stats.json").write_text(
            json.dumps(stats_payload, indent=2),
            encoding="utf-8",
        )

        (self.out_dir / "top_corpus.json").write_text(
            json.dumps(top_payload, indent=2),
            encoding="utf-8",
        )

        (self.out_dir / "coverage.json").write_text(
            json.dumps(coverage_payload, indent=2),
            encoding="utf-8",
        )

        (self.out_dir / "bugs_found.json").write_text(
            json.dumps(bugs_payload, indent=2),
            encoding="utf-8",
        )

    def _board_metrics_payload(self) -> Dict[str, Dict[str, float]]:
        payload: Dict[str, Dict[str, float]] = {}

        for board_size in self.board_sizes:
            samples = float(self.stats.get(f"board_initial_samples_{board_size}", 0))
            total_time = float(self.stats.get(f"board_initial_time_{board_size}", 0.0))
            new_coverage = float(self.stats.get(f"board_initial_new_coverage_{board_size}", 0))
            bug_hits = float(self.stats.get(f"board_initial_bug_hits_{board_size}", 0))
            unique_bugs = float(self.stats.get(f"board_initial_unique_bugs_{board_size}", 0))

            safe_time = max(total_time, 0.001)
            safe_samples = max(samples, 1.0)

            payload[str(board_size)] = {
                "samples": samples,
                "total_time": total_time,
                "avg_execution_time": total_time / safe_samples,
                "samples_per_second": samples / safe_time,
                "new_coverage": new_coverage,
                "coverage_per_sample": new_coverage / safe_samples,
                "coverage_per_second": new_coverage / safe_time,
                "bug_hits": bug_hits,
                "bug_hits_per_sample": bug_hits / safe_samples,
                "bug_hits_per_second": bug_hits / safe_time,
                "unique_bugs": unique_bugs,
                "bugs_per_sample": unique_bugs / safe_samples,
                "bugs_per_second": unique_bugs / safe_time,
                "gui_events": float(self.stats.get(f"board_initial_gui_events_{board_size}", 0)),
                "gui_valid_clicks": float(self.stats.get(f"board_initial_valid_clicks_{board_size}", 0)),
                "gui_occupied_clicks": float(self.stats.get(f"board_initial_occupied_clicks_{board_size}", 0)),
                "gui_redraws": float(self.stats.get(f"board_initial_redraws_{board_size}", 0)),
                "gui_status_updates": float(self.stats.get(f"board_initial_status_updates_{board_size}", 0)),
                "gui_resets": float(self.stats.get(f"board_initial_resets_{board_size}", 0)),
            }

        return payload


def parse_board_sizes(value: str) -> List[int]:
    result: List[int] = []

    for part in value.split(","):
        part = part.strip()
        if not part:
            continue

        size = int(part)
        if size < 3 or size > 8:
            raise argparse.ArgumentTypeError(
                f"Board size non valida: {size}. Usa valori tra 3 e 8."
            )

        result.append(size)

    if not result:
        raise argparse.ArgumentTypeError("Devi indicare almeno una board size.")

    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UI/action coverage-guided fuzzer per Havannah RLC + GUI Tkinter."
    )

    parser.add_argument(
        "--target",
        choices=TARGETS,
        default="gui",
        help="Target da fuzzare: model o gui. Default: gui.",
    )

    parser.add_argument(
        "--mode",
        choices=MODES,
        default="coverage_guided_rate",
        help="Modalità di fuzzing.",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=10_000,
        help="Numero massimo di iterazioni di fuzzing.",
    )

    parser.add_argument(
        "--time-budget-seconds",
        type=float,
        default=None,
        help="Budget massimo in secondi. Utile per esperimenti confrontabili coi paper.",
    )

    parser.add_argument(
        "--board-sizes",
        type=parse_board_sizes,
        default=parse_board_sizes("3,4,5,6,7,8"),
        help="Lista board sizes separate da virgola. Esempio: 3,4,5",
    )

    parser.add_argument(
        "--max-len",
        type=int,
        default=80,
        help="Lunghezza massima della sequenza di azioni.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed random opzionale per rendere il run riproducibile.",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("fuzz_out"),
        help="Cartella dove salvare output.",
    )

    parser.add_argument(
        "--gui-file",
        type=Path,
        default=None,
        help="File GUI da testare. Per gli esperimenti usa src/gui_buggy.py.",
    )

    parser.add_argument(
        "--report-every",
        type=int,
        default=500,
        help="Ogni quante iterazioni stampare un report.",
    )

    parser.add_argument(
        "--mutation-rounds",
        type=int,
        default=1,
        help="Numero base di mutazioni per candidato.",
    )

    parser.add_argument(
        "--run-id",
        type=str,
        default="run_0",
        help="Identificatore del run, utile per esperimenti multipli.",
    )

    parser.add_argument(
        "--disable-injected-bugs",
        action="store_true",
        help="Disabilita i bug artificiali nella GUI buggy.",
    )

    parser.add_argument(
        "--enable-model-invariants",
        action="store_true",
        help="Abilita l'oracle sul modello Rulebook (bug logici reali, es. BUG_MODEL_*).",
    )

    parser.add_argument(
        "--bug-variant-mod",
        type=int,
        default=1,
        help=(
            "Parametro X per i bug sintetici: synthetic_bug_id = base_bug_id + "
            "(stable_hash(contesto bug) mod X). Usa 1 per il comportamento storico."
        ),
    )

    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.iterations <= 0:
        parser.error("--iterations deve essere > 0")

    if args.time_budget_seconds is not None and args.time_budget_seconds <= 0:
        parser.error("--time-budget-seconds deve essere > 0")

    if args.max_len <= 0:
        parser.error("--max-len deve essere > 0")

    if args.report_every <= 0:
        parser.error("--report-every deve essere > 0")

    if args.mutation_rounds <= 0:
        parser.error("--mutation-rounds deve essere > 0")

    if args.bug_variant_mod <= 0:
        parser.error("--bug-variant-mod deve essere > 0")

    engine = UIFuzzEngine(
        target=args.target,
        mode=args.mode,
        iterations=args.iterations,
        time_budget_seconds=args.time_budget_seconds,
        board_sizes=args.board_sizes,
        max_len=args.max_len,
        seed=args.seed,
        out_dir=args.out_dir,
        report_every=args.report_every,
        mutation_rounds=args.mutation_rounds,
        run_id=args.run_id,
        enable_injected_bugs=not args.disable_injected_bugs,
        enable_model_invariants=args.enable_model_invariants,
        gui_file=args.gui_file,
        bug_variant_mod=args.bug_variant_mod,
    )

    engine.fuzz()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
