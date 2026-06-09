import math
import sys
import tkinter as tk
from pathlib import Path


def load_wrapper():
    build_dir = Path(__file__).resolve().parent.parent / "build"
    sys.path.insert(0, str(build_dir))
    import wrapper  
    return wrapper


STRUCTURE_NAMES = {1: "bridge", 2: "fork", 3: "ring"}
STONE_COLORS = {1: ("#f7f7f7", "#cfcfcf"), 2: ("#111111", "#333333")}


class HavannahGUI:
    def __init__(self, initial_board_size=8, test_mode=False, show_window=True):        
        self.wrapper = load_wrapper()
        self.hex_size = 26.0
        self.margin = 48.0
        self.positions = {}
        self.board_size = None
        self.session = None
        self.game = None
        self.test_mode = test_mode

        self.root = tk.Tk()
        self.root.title("Havannah")
        self.status_var = tk.StringVar(value="")
        self.info_var = tk.StringVar(value="")
        self.board_label_var = tk.StringVar(value="")

        self._build_layout()

        if self.test_mode:
            if not show_window:
                self.root.withdraw()
            self._start_session(initial_board_size)
        else:
            self._reset_game(initial=True)

    def _build_layout(self):
        self.main_frame = tk.Frame(self.root, padx=10, pady=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.top_bar = tk.Frame(self.main_frame)
        self.top_bar.pack(fill=tk.X, pady=(0, 8))
        tk.Label(self.top_bar, textvariable=self.status_var, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(self.top_bar, text="Nuova partita", command=self._reset_game).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Label(self.top_bar, textvariable=self.board_label_var, anchor="e").pack(side=tk.RIGHT, padx=(8, 4))

        self.canvas = tk.Canvas(self.main_frame, width=900, height=820, bg="#f5f3eb", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.info = tk.Label(self.main_frame, textvariable=self.info_var, anchor="w", justify=tk.LEFT)
        self.info.pack(fill=tk.X, pady=(8, 0))
        self.info_var.set("Click su un esagono per giocare. Bianco inizia. Vittoria con bridge, fork o ring.")


    def _bounded(self, cls, value):
        v = cls()
        v.value = value
        return v

    def _ask_board_size(self, initial=False):
        for widget in (self.top_bar, self.canvas, self.info):
            widget.pack_forget()

        panel = tk.Frame(self.main_frame, padx=16, pady=16)
        panel.pack(fill=tk.BOTH, expand=True)

        selected_size = tk.IntVar(value=self.board_size if self.board_size is not None else 8)
        done_var = tk.IntVar(value=0)

        title = "Scegli la dimensione della board" if initial else "Nuova partita"
        tk.Label(panel, text=title, font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        tk.Label(panel, text="La partita iniziera' subito dopo la selezione.", justify=tk.LEFT, pady=8).pack(anchor="w")

        sizes = tk.Frame(panel, pady=4)
        sizes.pack(fill=tk.X)
        for size in range(3, 9):
            tk.Radiobutton(sizes, text=str(size), variable=selected_size, value=size,
                           indicatoron=False, width=4, padx=6, pady=6).pack(side=tk.LEFT, padx=4)

        buttons = tk.Frame(panel, pady=8)
        buttons.pack(fill=tk.X)
        if not initial:
            tk.Button(buttons, text="Annulla", command=lambda: done_var.set(-1)).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Inizia", command=lambda: done_var.set(1)).pack(side=tk.RIGHT, padx=(0, 8))

        self.root.wait_variable(done_var)
        panel.destroy()

        self.top_bar.pack(fill=tk.X, pady=(0, 8))
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.info.pack(fill=tk.X, pady=(8, 0))

        return selected_size.get() if done_var.get() == 1 else None

    def _start_session(self, board_size):
        session = self.wrapper.session()
        size_arg = self._bounded(self.wrapper.BIntT3T8T, board_size)
        if not session.can_choose_board_size(size_arg):
            raise ValueError(f"Board size non valida: {board_size}")
        session.choose_board_size(size_arg)

        self.session = session
        self.game = self.session.game.board
        self.board_size = board_size
        self.board_label_var.set(f"Board: {board_size}")

        self._compute_positions()
        self._draw_static_board()
        self._redraw_stones()
        self._refresh_status()

    def _compute_positions(self):
        if self.game is None:
            return
        factor_x = self.hex_size * math.sqrt(3.0)
        coords = [(i,
                   factor_x * (self.game.cell_q(i) + self.game.cell_r(i) / 2.0),
                   self.hex_size * 1.5 * self.game.cell_r(i))
                  for i in range(self.game.cell_count())]
        xs = [x for _, x, _ in coords]
        ys = [y for _, _, y in coords]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        self.positions = {i: (x - min_x + self.margin, y - min_y + self.margin) for i, x, y in coords}
        width = (max_x - min_x) + (self.margin * 2.0)
        height = (max_y - min_y) + (self.margin * 2.0)
        self.canvas.config(width=int(width), height=int(height))

    def _hex_points(self, cx, cy):
        points = []
        for k in range(6):
            angle = math.radians(30.0 + 60.0 * k)
            points += [cx + self.hex_size * math.cos(angle), cy + self.hex_size * math.sin(angle)]
        return points

    def _bind_cell_click(self, tag, index):
        self.canvas.tag_bind(tag, "<Button-1>", lambda _e: self._on_cell_click(index))

    def _draw_static_board(self):
        self.canvas.delete("all")
        for index, (cx, cy) in self.positions.items():
            tag = f"cell_{index}"
            self.canvas.create_polygon(self._hex_points(cx, cy), fill="#d8c7a2", outline="#4f4a3a",
                                       width=1.5, tags=(tag, "cell"))
            self._bind_cell_click(tag, index)

    def _redraw_stones(self):
        self.canvas.delete("stone")
        radius = self.hex_size * 0.62
        for index, (cx, cy) in self.positions.items():
            state = self.game.get_cell(index)
            if state == 0:
                continue
            fill, outline = STONE_COLORS[state]
            tag = f"cell_{index}"
            self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                                    fill=fill, outline=outline, width=2.0, tags=("stone", tag))
            self._bind_cell_click(tag, index)

    def _winner_structure(self):
        winner = "Bianco" if self.game.winner_player() == 1 else "Nero"
        structure = STRUCTURE_NAMES.get(self.game.win_structure(), "unknown")
        return winner, structure

    def _refresh_status(self, event_message=""):
        if self.game is None:
            self.status_var.set("Seleziona la dimensione della board per iniziare.")
            return
        if self.game.is_done_game():
            if self.game.winner_player() == 0:
                turn_text = "Partita conclusa: patta."
            else:
                winner, structure = self._winner_structure()
                turn_text = f"Partita conclusa: {winner} vince con {structure}."
        else:
            current = "Bianco" if self.game.current_player() == 1 else "Nero"
            turn_text = f"Turno: {current}"
        self.status_var.set(f"{turn_text} | {event_message}" if event_message else turn_text)

    def _on_cell_click(self, index):
        if self.session is None or self.game is None:
            return
        if self.game.is_done_game():
            self._refresh_status("Partita gia' terminata.")
            return
        move = self._bounded(self.wrapper.BIntT0T169T, index)
        if not self.session.can_play_move(move):
            self._refresh_status("Cella occupata." if self.game.get_cell(index) != 0 else "Mossa non valida.")
            return
        self.session.play_move(move)
        self._redraw_stones()
        if self.game.is_done_game():
            if self.game.winner_player() == 0:
                msg = "Patta: board piena."
            else:
                winner, structure = self._winner_structure()
                msg = f"Vittoria {winner} con {structure}."
            self._refresh_status(msg)
            return
        self._refresh_status()

    def _reset_game(self, initial=False):
        board_size = self._ask_board_size(initial=initial)
        if board_size is None:
            if initial:
                self.root.destroy()
            return
        self._start_session(board_size)

    def fuzz_reset_to_size(self, board_size):
        if board_size < 3 or board_size > 8:
            raise ValueError(f"Board size non valida: {board_size}")
        self._start_session(board_size)
        self.root.update_idletasks()    

    def fuzz_click_cell(self, index):
        self._on_cell_click(index)
        self.root.update_idletasks()    

    def run(self):
        self.root.mainloop()


def main():
    HavannahGUI().run()


if __name__ == "__main__":
    main()
