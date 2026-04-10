import collections.vector
import action

cls HavannahGame:
  # ============================================================
  # SEZIONE: STATO DEL GIOCO
  # - campi permanenti della partita
  # ============================================================
  
  # Board di 169 celle.
  # Convenzione:
  # 0 = vuota
  # 1 = bianco
  # 2 = nero
  # La capacita' massima corrisponde a board_size = 8.
  Int[169] cells

  # Coordinate assiali per ogni cella (geometria esagonale).
  Int[169] q_coords
  Int[169] r_coords

  # Matrice dei vicini precomputati (169 x 6).
  Int[169][6] neighbors

  # Marcatori temporanei usati durante la DFS del ring.
  Bool[169] ring_marks

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

  # Dimensione base runtime della board.
  Int base_size_value

  # ============================================================
  # FINE SEZIONE: STATO DEL GIOCO
  # ============================================================

  # ============================================================
  # SEZIONE: COSTANTI E INIZIALIZZAZIONE
  # - dimensioni board
  # - init stato
  # - costruzione geometria assiale
  # ============================================================

  # Dimensione base.
  fun base_size() -> Int:
    return self.base_size_value

  # Raggio della board (per base_size=8 -> raggio 7).
  fun radius() -> Int:
    return self.base_size() - 1
    
  # Numero celle totale per questa configurazione. celle = 3R(R + 1) + 1 = (3 x 7 x 8) + 1 = 169
  fun cell_count() -> Int:
    let r = self.radius()
    return (3 * r * (r + 1)) + 1

  # Inizializza una nuova partita con dimensione base configurabile.
  fun init(Int board_size):
    assert(board_size >= 3 and board_size <= 8, "Unsupported Havannah board size")
    self.base_size_value = board_size
    # Inizializza esplicitamente i buffer della board.
    let i = 0
    while i < 169:
      self.cells[i] = 0
      self.ring_marks[i] = false
      i = i + 1

    # Stato logico iniziale.
    self.white_turn = true
    self.done = false
    self.winner = 0
    self.win_kind = 0
    self.moves_played = 0
    self._initialize_geometry()

  # Costruisce la mappa indice lineare -> coordinate assiali (q,r).
  fun _initialize_geometry():
    # index = quante celle valide abbiamo scritto finora.
    let index = 0

    # q scorre tutte le "colonne assiali" da sinistra a destra.
    # Range completo: [-R, R].
    let q = -self.radius()
    while q <= self.radius():
      # Primo vincolo su r: |r| <= R  => r >= -R.
      let min_r = -self.radius()

      # Secondo vincolo su r viene da |s| <= R con s = -q-r.
      # Da -R <= -q-r <= R si ottiene:
      #   r >= -q-R   e   r <= -q+R
      # Qui si prende il bound inferiore candidato: -q-R.
      let candidate_min = -q - self.radius()
      
      # Bound inferiore finale:
      # r >= max(-R, -q-R)
      if candidate_min > min_r:
        min_r = candidate_min

      # Primo vincolo superiore su r: |r| <= R  => r <= R.
      let max_r = self.radius()

      # Bound superiore candidato da |s| <= R: r <= -q+R.
      let candidate_max = -q + self.radius()

      # Bound superiore finale:
      # r <= min(R, -q+R)
      if candidate_max < max_r:
        max_r = candidate_max

      # Ora r percorre solo le celle valide della colonna q.
      let r = min_r
      while r <= max_r:
        # Salva la posizione assiale della cella lineare "index".
        self.q_coords[index] = q
        self.r_coords[index] = r

        # Prossimo slot lineare.
        index = index + 1

        # Prossima r nella stessa colonna q.
        r = r + 1

      # Passa alla colonna q successiva.
      q = q + 1

    # Check di correttezza geometrica.
    # Deve aver scritto esattamente 169 celle (con R=7).
    assert(index == self.cell_count(), "Invalid Havannah geometry")

    # Precompute dei vicini in stile OpenSpiel: lookup O(1) a runtime.
    let i = 0
    while i < self.cell_count():
      let q = self.q_coords[i]
      let r = self.r_coords[i]
      self.neighbors[0][i] = self._find_index(q + 1, r)
      self.neighbors[1][i] = self._find_index(q + 1, r - 1)
      self.neighbors[2][i] = self._find_index(q, r - 1)
      self.neighbors[3][i] = self._find_index(q - 1, r)
      self.neighbors[4][i] = self._find_index(q - 1, r + 1)
      self.neighbors[5][i] = self._find_index(q, r + 1)
      i = i + 1

  # ============================================================
  # FINE SEZIONE: COSTANTI E INIZIALIZZAZIONE
  # ============================================================


  # ============================================================
  # SEZIONE: API PUBBLICA (LETTURA STATO)
  # - metodi di lettura sicuri usati da esterno
  # ============================================================

  # Verifica se un indice e' dentro la board.
  fun is_valid_index(Int index) -> Bool:
    return index >= 0 and index < self.cell_count()

  # Contenuto cella:
  # 0 vuota, 1 bianco, 2 nero, -1 indice non valido
  fun get_cell(Int index) -> Int:
    if !self.is_valid_index(index):
      return -1
    return self.cells[index]

  # Ritorna coordinata q della cella (0 se indice non valido).
  fun cell_q(Int index) -> Int:
    if !self.is_valid_index(index):
      return 0
    return self.q_coords[index]

  # Ritorna coordinata r della cella (0 se indice non valido).
  fun cell_r(Int index) -> Int:
    if !self.is_valid_index(index):
      return 0
    return self.r_coords[index]

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

  # ============================================================
  # FINE SEZIONE: API PUBBLICA (LETTURA STATO)
  # ============================================================


  # ============================================================
  # SEZIONE: NAVIGAZIONE BOARD (UTILITY GENERALI)
  # ============================================================

  # Cerca l'indice lineare associato a coordinate assiali (q,r).
  # Ritorna -1 se la coppia non esiste sulla board.
  fun _find_index(Int q, Int r) -> Int:
    let i = 0
    while i < self.cell_count():
      if self.q_coords[i] == q and self.r_coords[i] == r:
        return i
      i = i + 1
    return -1

  # Ritorna l'indice del vicino in una delle 6 direzioni.
  # Se il vicino e' fuori board, ritorna -1.
  fun _neighbor_index(Int index, Int direction) -> Int:
    if !self.is_valid_index(index):
      return -1
    if direction < 0 or direction >= 6:
      return -1
    return self.neighbors[direction][index]

  # ============================================================
  # FINE SEZIONE: NAVIGAZIONE BOARD
  # ============================================================


  # ============================================================
  # SEZIONE: BRIDGE OR FORK
  # ============================================================

  # Restituisce l'id del corner toccato da (q,r), oppure -1.
  fun _corner_id(Int q, Int r) -> Int:
    let radius = self.radius()
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

  # Restituisce l'id del lato toccato da (q,r), escludendo i corner, oppure -1.
  fun _edge_id(Int q, Int r) -> Int:
    if self._corner_id(q, r) != -1:
      return -1

    let radius = self.radius()
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

  # Controlla la componente connessa del player che contiene root_index (root_index è l’indice della cella da cui si parte per esplorare la componente connessa).
  # Ritorna:
  # 0 = nessuna struttura
  # 1 = bridge (>=2 corner)
  # 2 = fork   (>=3 edge)
  fun _bridge_or_fork_from(Int root_index, Int player) -> Int:
    if !self.is_valid_index(root_index) or self.cells[root_index] != player:
      return 0

    let visited : Bool[169]
    let i = 0
    while i < self.cell_count():
      visited[i] = false
      i = i + 1

    let queue : Int[169]
    let head = 0
    let tail = 0

    # Segna quali corner/edge sono toccati dalla componente.
    let touched_corners : Bool[6]
    let touched_edges : Bool[6]
    let marker = 0
    while marker < 6:
      touched_corners[marker] = false
      touched_edges[marker] = false
      marker = marker + 1

    visited[root_index] = true
    queue[tail] = root_index
    tail = tail + 1

    while head < tail:
      let current = queue[head]
      head = head + 1

      let q = self.q_coords[current]
      let r = self.r_coords[current]

      let corner = self._corner_id(q, r)
      if corner != -1:
        touched_corners[corner] = true

      let edge = self._edge_id(q, r)
      if edge != -1:
        touched_edges[edge] = true

      let direction = 0
      while direction < 6:
        let neighbor = self._neighbor_index(current, direction)
        if neighbor != -1 and !visited[neighbor] and self.cells[neighbor] == player:
          visited[neighbor] = true
          queue[tail] = neighbor
          tail = tail + 1
        direction = direction + 1

    # Conta quanti corner/edge distinti sono stati toccati.
    let corner_count = 0
    let edge_count = 0
    marker = 0
    while marker < 6:
      if touched_corners[marker]:
        corner_count = corner_count + 1
      if touched_edges[marker]:
        edge_count = edge_count + 1
      marker = marker + 1

    if corner_count >= 2:
      return 1
    if edge_count >= 3:
      return 2
    return 0

  # ============================================================
  # FINE SEZIONE: BRIDGE OR FORK
  # ============================================================

  # ============================================================
  # SEZIONE: RING (rilevazione ciclo)
  # ============================================================

  # Normalizza una direzione nel range [0, 5].
  fun _normalize_direction(Int direction) -> Int:
    let normalized = direction
    while normalized < 0:
      normalized = normalized + 6
    while normalized >= 6:
      normalized = normalized - 6
    return normalized

  # Verifica se start e target sono connessi passando solo su celle del player,
  # senza usare la cella forbidden_index.
  fun _is_connected_avoiding(Int start, Int target, Int forbidden_index, Int player) -> Bool:
    if start == target:
      return true
    if start == forbidden_index or target == forbidden_index:
      return false

    let visited : Bool[169]
    let i = 0
    while i < self.cell_count():
      visited[i] = false
      i = i + 1

    let queue : Int[169]
    let head = 0
    let tail = 0
    visited[start] = true
    queue[tail] = start
    tail = tail + 1

    while head < tail:
      let current = queue[head]
      head = head + 1

      let direction = 0
      while direction < 6:
        let neighbor = self._neighbor_index(current, direction)
        if neighbor != -1 and neighbor != forbidden_index and !visited[neighbor] and self.cells[neighbor] == player:
          if neighbor == target:
            return true
          visited[neighbor] = true
          queue[tail] = neighbor
          tail = tail + 1
        direction = direction + 1

    return false

  # True se la mossa collega due vicini che erano gia' connessi senza la mossa stessa.
  fun _already_joined(Int move_index, Int player) -> Bool:
    let neighbors : Int[6]
    let count = 0
    let direction = 0
    while direction < 6:
      let neighbor = self._neighbor_index(move_index, direction)
      if neighbor != -1 and self.cells[neighbor] == player:
        neighbors[count] = neighbor
        count = count + 1
      direction = direction + 1

    if count < 2:
      return false

    let i = 0
    while i < count:
      let j = i + 1
      while j < count:
        if self._is_connected_avoiding(neighbors[i], neighbors[j], move_index, player):
          return true
        j = j + 1
      i = i + 1

    return false

  # DFS direzionale per rilevare un ring.
  fun _check_ring_dfs(Int index, Int left, Int right, Int player) -> Bool:
    if index == -1:
      return false
    if self.cells[index] != player:
      return false
    if self.ring_marks[index]:
      return true

    self.ring_marks[index] = true
    let success = false
    let direction = left
    while direction <= right:
      if !success:
        let dir = self._normalize_direction(direction)
        let neighbor = self._neighbor_index(index, dir)
        if self._check_ring_dfs(neighbor, dir - 1, dir + 1, player):
          success = true
      direction = direction + 1

    self.ring_marks[index] = false
    return success

  # True se dalla mossa emerge un ring del player.
  fun _has_ring_from(Int move_index, Int player) -> Bool:
    let i = 0
    while i < self.cell_count():
      self.ring_marks[i] = false
      i = i + 1

    return self._check_ring_dfs(move_index, 0, 3, player)

  # ============================================================
  # FINE SEZIONE: RING
  # ============================================================
  
  # True se non ci sono piu' celle vuote.
  fun _is_board_full() -> Bool:
    let i = 0
    while i < self.cell_count():
      if self.cells[i] == 0:
        return false
      i = i + 1
    return true

  # Verifica bridge/fork e poi ring.
  fun _detect_win_from_move(Int move_index, Int player) -> Int:
    let structure = self._bridge_or_fork_from(move_index, player)
    if structure != 0:
      return structure

    if self._already_joined(move_index, player) and self._has_ring_from(move_index, player):
      return 3

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

# Crea una partita nuova con dimensione base configurabile.
fun new_game(Int board_size) -> HavannahGame:
  let game : HavannahGame
  game.init(board_size)
  return game

# ============================================================
# SEZIONE: INTERFACCIA RULEBOOK ACT
# - espone play_move come action function per fuzzer/tooling
# ============================================================

@classes
act play(Int board_size) -> Game:
  frm board = new_game(board_size)

  while !board.is_done_game():
    act play_move(BInt<0, 169> index) {
      index.value < board.cell_count() and board.get_cell(index.value) == 0
    }

    board.play_move(index.value)

fun get_currfuzzent_player(Game g) -> Int:
  if g.is_done():
    return -4
  return g.board.current_player() - 1

fun score(Game g, Int player_id) -> Float:
  if !g.is_done():
    return 0.0
  if g.board.winner_player() == 0:
    return 0.0
  if g.board.winner_player() == player_id + 1:
    return 1.0
  return -1.0

fun get_num_players() -> Int:
  return 2

fun fuzz(Vector<Byte> input):
  if input.size() == 0:
    return

  let state = play(8)
  let action_value : AnyGameAction
  parse_and_execute(state, action_value, input)

# Entrypoint minimo di controllo.
fun main() -> Int:
  let game = new_game(8)
  if game.cell_count() == 169 and game.base_size() == 8:
    return 0
  return 1