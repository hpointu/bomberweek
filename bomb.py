import random
import time
from collections import defaultdict
from enum import Flag
from typing import Tuple, NamedTuple, Callable, Dict, List, Optional

_uid = 0

CELL_SIZE = 16
CSIZE = 14
PSIZE = 12, 12
BSIZE = 16, 16

BOMB_TTL = 3
FLAME_TTL = 0.3

NEW_COLL = 40

Cell = Tuple[int, int]
Coords = Tuple[float, float]

Effect = List[Dict]
Action = Callable[[float], Effect]


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float


class Direction(Flag):
    UP = 1
    RIGHT = 2
    DOWN = 4
    LEFT = 8


class Player(NamedTuple):
    pos: Coords
    pid: str
    bomb_limit: int = 1
    bomb_radius: int = 1
    alive: bool = True
    speed_boots: bool = False
    moving: bool = False
    direction: int = Direction.DOWN.value
    moving_time: float = 0

    @property
    def speed(self):
        return 55 if self.speed_boots else 40

    @property
    def rect(self):
        x, y = self.pos
        return Rect(x+2, y, *PSIZE)


class Bomb(NamedTuple):
    id: int
    player: str
    pos: Coords
    birth: float
    radius: int
    ttl: float = BOMB_TTL

    @property
    def rect(self):
        return Rect(*self.pos, *BSIZE)


class Wall(NamedTuple):
    rect: Rect


class Collectible(NamedTuple):
    kind: str
    pos: Coords

    @property
    def rect(self):
        return Rect(*self.pos, CSIZE, CSIZE)


class Flame(NamedTuple):
    pos: Coords
    birth: float
    kind: str

    @property
    def rect(self):
        return Rect(*self.pos, CELL_SIZE, CELL_SIZE)


def coll_speed_boots(p: Player) -> Player:
    return p._replace(speed_boots=True)


def coll_mega_bomb(p: Player) -> Player:
    r = p.bomb_radius
    return p._replace(bomb_radius=r+1)


def coll_extra_bomb(p: Player) -> Player:
    limit = p.bomb_limit
    return p._replace(bomb_limit=limit+1)


COLLECTIBLES = {
    '~': coll_speed_boots,
    '!': coll_mega_bomb,
    '+': coll_extra_bomb,
}


def uid():
    global _uid
    _uid += 1
    return _uid


def is_collectible(c):
    return c in '+~!'


def is_wall(cell_char):
    return cell_char in '12'


def is_breakable(cell_char):
    return cell_char == '2'


def split_list(l, pred) -> Tuple[list, list]:
    good, bad = [], []
    for e in l:
        if pred(e):
            good.append(e)
        else:
            bad.append(e)
    return good, bad


def collides(r1: Rect, r2: Rect) -> bool:
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    return (x1 < x2 + w2) and \
        (x1 + w1 > x2) and \
        (y1 < y2 + h2) and \
        (y1 + h1 > y2)


def load_players(players):
    return {name: Player(*p) for name, p in players.items()}


def load_list(cls):
    def _load(elems):
        return [cls(*e) for e in elems]
    return _load


class GameState:
    fields = {
        'players': load_players,
        'bombs': load_list(Bomb),
        'cells': list,
        'width': int,
        'height': int,
        'running': bool,
        'flames': load_list(Flame),
        'collectibles': load_list(Collectible),
    }

    def __init__(self):
        self.running = False
        self.players = {}
        self.bombs = []
        self.flames = []
        self.collectibles = []
        self._can_walk = defaultdict(set)
        self._last_coll = time.time()

    def cell_from_idx(self, idx) -> Cell:
        """ Cell index to Grid coords """
        return idx % self.width, idx // self.width

    def cell_idx(self, cell: Cell) -> int:
        i, j = cell
        return int(j) * self.width + int(i)

    def cell_coords(self, cell: Cell) -> Coords:
        """ Grid coords to World coords """
        i, j = cell
        return i * CELL_SIZE, j * CELL_SIZE

    def cell_from_coords(self, coords: Coords) -> Cell:
        """ World coords to Grid coords """
        x, y = coords
        return x // CELL_SIZE, y // CELL_SIZE

    def generate_flames(self, bomb: Bomb) -> List[Cell]:
        now = time.time()
        cell = self.cell_from_coords(bomb.pos)
        flames = [Flame(self.cell_coords(cell), now, 'c')]
        hit_indices = []
        deltas = [(-1, 0, 'h'), (0, -1, 'v'),
                  (1, 0, 'h'), (0, 1, 'v')]

        def _dir_flames(dx, dy, kind):
            f, h = [], None
            c = cell
            for r in range(bomb.radius):
                c = c[0] + dx, c[1] + dy
                idx = self.cell_idx(c)
                if not (0 <= idx < self.width * self.height):
                    break
                if is_wall(self.cells[idx]):
                    h = idx
                    if is_breakable(self.cells[idx]):
                        f.append(Flame(self.cell_coords(c), now, 'w'))
                    break
                f.append(Flame(self.cell_coords(c), now, kind))
            return f, h

        for d in deltas:
            fs, h = _dir_flames(*d)
            flames += fs
            if h is not None:
                hit_indices.append(h)

        return flames, hit_indices

    def cell_center(self, cell: Cell) -> Coords:
        x, y = self.cell_coords(cell)
        return x + CELL_SIZE/2, y + CELL_SIZE/2

    def spawn_player(self, player_name):
        loc = self.spawn_points.pop()
        self.players[player_name] = Player(
            pid=self.cells[loc],
            pos=self.cell_coords(self.cell_from_idx(loc))
        )
        return self.cells[loc]

    def random_collectible(self):
        found = None
        while not found:
            i = random.choice([i for i, c in enumerate(self.cells)
                               if not is_wall(c)])
            kind = random.choice('~++!!')
            coll = self.create_collectible(i, kind)
            forbid = self._walls + list(self.players.values()) \
                + self.collectibles
            if not any(collides(coll.rect, o.rect) for o in forbid):
                found = coll
        return found

    def add_collectible(self, coll):
        self.collectibles.append(coll)

    def remove_player(self, player_name):
        if player_name in self.players:
            self.players.pop(player_name)

    def set_level(self, w, h, cells):
        self.width = w
        self.height = h
        self.cells = cells
        self.spawn_points = [
            i for i, c in enumerate(cells)
            if c in 'abcd'
        ]
        self.update_wall_rects()
        self.update_collectible_rects()
        self._last_coll = time.time()

    def update_collectible_rects(self):
        self.collectibles = [
            self.create_collectible(i, c)
            for i, c in enumerate(self.cells)
            if is_collectible(c)
        ]

    def update_wall_rects(self):
        self._walls = [
            Wall(Rect(*self.cell_coords(self.cell_from_idx(i)),
                      CELL_SIZE, CELL_SIZE))
            for i, c in enumerate(self.cells) if is_wall(c)
        ]

    def dump(self, *fields):
        fields = fields or self.fields.keys()
        return {
            f: getattr(self, f)
            for f in fields
        }

    def load(self, data):
        for k, v in data.items():
            if k in self.fields:
                setattr(self, k, self.fields[k](v))

    def tick(self, dt) -> Optional[Effect]:
        if not self.running:
            return

        effect = []
        state = {}
        now = time.time()

        new_coll_time = random.randint(NEW_COLL, NEW_COLL + 15)
        if int(now - self._last_coll) > new_coll_time:
            self.add_collectible(self.random_collectible())
            self._last_coll = now
            state.update(self.dump('collectibles'))

        def touch_flame(o):
            return any(collides(f.rect, o.rect)
                       for f in self.flames)

        def should_explode(b):
            return touch_flame(b) or now - b.birth >= b.ttl

        exploding_bombs, living_bombs = split_list(self.bombs, should_explode)

        # Make bombs explode
        broken_walls = []
        if exploding_bombs:
            for b in exploding_bombs:
                flames, broken = self.generate_flames(b)
                self.flames += flames
                broken_walls += broken

            if self.break_walls(broken_walls):
                state.update(self.dump('cells', 'collectibles'))

            self.bombs = living_bombs
            state.update(self.dump('bombs'))
            state.update(self.dump('flames'))

        # check dead people
        for pname, player in self.players.items():
            if touch_flame(player):
                self.players[pname] = player._replace(alive=False)
                state.update(self.dump('players'))
            # ah, and pick collectibles
            for coll in list(self.collectibles):
                if collides(player.rect, coll.rect):
                    self.collectibles.remove(coll)
                    fn = COLLECTIBLES[coll.kind]
                    self.players[pname] = fn(player)
                    state.update(self.dump('collectibles'))

        # clean old flames
        n_flames = len(self.flames)
        self.flames = [f for f in self.flames
                       if now - f.birth < FLAME_TTL]
        if n_flames != len(self.flames):
            state.update(self.dump('flames'))

        survivors = [name for name, p in self.players.items() if p.alive]
        nb_survivors = len(survivors)

        if nb_survivors < 1:
            self.running = False
            effect.append({'code': 'fatal', 'text': "No player alive!"})
            state.update(self.dump())
        elif nb_survivors == 1:
            self.running = False
            # TODO : probably other type of message than fatal
            effect.append({'code': 'fatal',
                           'text': f"Wouhou ! {survivors[0]} is the Winner !"})
            state.update(self.dump())

        if state:
            effect.append({'code': 'update', 'state': state})

        return effect

    def move_player(self, player_name, direction, dt) -> Effect:
        p = self.players[player_name]
        if not p.alive:
            return

        x, y = p.pos

        def _move(dx, dy):
            # are we moving out a new bomb ?
            for walkable in list(self._can_walk[player_name]):
                obj = self.object_by_id(walkable)
                if not obj or not collides(obj.rect, p.rect):
                    self._can_walk[player_name].discard(walkable)

            # only move if not resluting in a wall
            np = p._replace(pos=(dx+x, dy+y))
            if not any(collides(wr.rect, np.rect)
                       for wr in self.obstacles(player_name)):
                return dx + x, dy + y

            return x, y

        s = p.speed * dt
        if Direction.UP in direction:
            x, y = _move(0, s)
        if Direction.RIGHT in direction:
            x, y = _move(s, 0)
        if Direction.DOWN in direction:
            x, y = _move(0, -s)
        if Direction.LEFT in direction:
            x, y = _move(-s, 0)

        p = p._replace(direction=direction.value,
                       moving_time=p.moving_time+dt)
        if p.pos != (x, y):
            p = p._replace(pos=(x, y))

        self.players[player_name] = p
        return [{'code': 'update',
                 'state': self.dump('players')}]

    def stop_moving(self, player_name):
        p = self.players[player_name]
        if not p.alive:
            return
        self.players[player_name] = p._replace(moving_time=0)
        return [{'code': 'update',
                 'state': self.dump('players')}]

    def drop_bomb(self, player_name):
        player = self.players[player_name]
        if not player.alive:
            return

        player_bombs = len([b for b in self.bombs
                            if b.player == player_name])
        if player.bomb_limit <= player_bombs:
            return

        px, py = player.pos
        cell = self.cell_from_coords((px+CELL_SIZE/2, py+CELL_SIZE/2))
        x, y = self.cell_center(cell)
        x -= BSIZE[0] // 2
        y -= BSIZE[1] // 2
        now = time.time()
        radius = player.bomb_radius
        bomb = Bomb(uid(), player_name, (x, y), now, radius)

        # allow players on bomb to move away from it
        on_bomb_players = [pname for pname, p in self.players.items()
                           if collides(p.rect, bomb.rect)]
        for pname in on_bomb_players:
            self._can_walk[pname].add(bomb.id)

        self.bombs.append(bomb)

        return [{'code': 'update',
                 'state': self.dump('bombs')}]

    def break_walls(self, wall_indices):
        effect = False
        for w in wall_indices:
            c = self.cells[w]
            if is_breakable(c):
                self.cells[w] = '0'
                kind = random.choice('000~0+0+0!0!000')
                if kind != '0':
                    coll = self.create_collectible(w, kind)
                    self.add_collectible(coll)
                effect = True
        if effect:
            self.update_wall_rects()
        return effect

    def create_collectible(self, index, kind):
        self.cells[index] = kind
        cell = self.cell_from_idx(index)
        x, y = self.cell_center(cell)
        pos = x - CELL_SIZE // 2, y - CELL_SIZE // 2
        return Collectible(kind, pos)

    def object_by_id(self, id):
        return next((i for i in self.identifiables if i.id == id), None)

    @property
    def identifiables(self):
        return self.bombs

    def obstacles(self, pname):
        return self._walls + [b for b in self.bombs
                              if b.id not in self._can_walk[pname]]


def action(gs: GameState, pname: str, data: dict) -> Action:
    code = data['code']
    if gs.running and code == 'move':
        return lambda dt: gs.move_player(pname, Direction(data['dir']), dt)
    elif gs.running and code == 'stop':
        return lambda dt: gs.stop_moving(pname)
    elif gs.running and code == 'drop_bomb':
        return lambda _: gs.drop_bomb(pname)


def load_level(filename):
    cells = []
    w, h = 0, 0
    with open(filename) as f:
        for j, line in enumerate(f):
            w = 0
            for i, cell in enumerate(line.strip()):
                cells.append(cell)
                w += 1
            h += 1
    return w, h, cells
