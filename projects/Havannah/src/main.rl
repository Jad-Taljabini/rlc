cls HavannahGame:
  # Board di 169 celle.
  # Convenzione:
  # 0 = vuota
  # 1 = bianco
  # 2 = nero
  Int[169] cells

  # true  -> turno del bianco
  # false -> turno del nero
  Bool white_turn

  # true se la partita e terminata
  Bool done

  # Vincitore:
  # 0 = nessuno
  # 1 = bianco
  # 2 = nero
  Int winner

  # Tipo vittoria:
  # 0 = nessuna
  # 1 = bridge
  # 2 = fork
  # 3 = ring
  Int win_kind

  # Numero di mosse giocate finora
  Int moves_played

  # Dimensione base.
  fun base_size() -> Int:
    return 8

  # Numero celle totale per questa configurazione.
  fun cell_count() -> Int:
    return 169

  # Reset completo dello stato partita.
  fun reset():
    # Svuota tutta la board.
    let i = 0
    while i < self.cell_count():
      self.cells[i] = 0
      i = i + 1

    # Reinizializza stato logico.
    self.white_turn = true
    self.done = false
    self.winner = 0
    self.win_kind = 0
    self.moves_played = 0

  # Verifica se un indice e' dentro la board.
  fun is_valid_index(Int index) -> Bool:
    return index >= 0 and index < self.cell_count()

  # Contenuto cella:
  # 0 vuota, 1 bianco, 2 nero, -1 indice non valido
  fun get_cell(Int index) -> Int:
    if !self.is_valid_index(index):
      return -1
    return self.cells[index]

  # Giocatore di turno: 1 bianco, 2 nero
  fun current_player() -> Int:
    if self.white_turn:
      return 1
    return 2

  # True se partita finita
  fun is_done_game() -> Bool:
    return self.done

  # Vincitore: 0 nessuno, 1 bianco, 2 nero
  fun winner_player() -> Int:
    return self.winner

  # Tipo vittoria: 0 nessuna, 1 bridge, 2 fork, 3 ring
  fun win_structure() -> Int:
    return self.win_kind

  # Numero mosse giocate
  fun move_count() -> Int:
    return self.moves_played
  
  # True se non ci sono piu' celle vuote.
  fun _is_board_full() -> Bool:
    let i = 0
    while i < self.cell_count():
      if self.cells[i] == 0:
        return false
      i = i + 1
    return true

  # Placeholder: per ora nessuna vittoria (bridge/fork/ring)
  fun _detect_win_from_move(Int move_index, Int player) -> Int:
    return 0

  # Codifica vittoria in status:
  # bianco 1..3, nero 4..6
  fun _encode_win_status(Int player, Int structure) -> Int:
    return ((player - 1) * 3) + structure

  # Imposta stato finale di vittoria e ritorna status
  fun _finalize_win(Int player, Int structure) -> Int:
    self.done = true
    self.winner = player
    self.win_kind = structure
    return self._encode_win_status(player, structure)

  # Applica una mossa.
  #  0: mossa valida senza vittoria
  #  1..3: vittoria bianco (bridge/fork/ring)
  #  4..6: vittoria nero (bridge/fork/ring)
  #  7: patta (board piena)
  # -1: indice non valido
  # -2: cella occupata
  # -3: partita gia' terminata
  fun play_move(Int index) -> Int:
    if self.done:
      return -3
    if !self.is_valid_index(index):
      return -1
    if self.cells[index] != 0:
      return -2

    let player = self.current_player()
    self.cells[index] = player
    self.moves_played = self.moves_played + 1

    let win_structure = self._detect_win_from_move(index, player)
    if win_structure != 0:
      return self._finalize_win(player, win_structure)

    if self._is_board_full():
      self.done = true
      self.winner = 0
      self.win_kind = 0
      return 7

    self.white_turn = !self.white_turn
    return 0

# Crea una partita nuova e la resetta.
fun new_game() -> HavannahGame:
  let game : HavannahGame
  game.reset()
  return game

# Entrypoint minimo di controllo.
fun main() -> Int:
  let game = new_game()
  if game.cell_count() == 169 and game.base_size() == 8:
    return 0
  return 1
