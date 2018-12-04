import asyncio
import json
import pyglet
import time
from pyglet.window import key
from pyglet.gl import *  # noqa

from bomb import GameState, Coords, Direction, is_wall, is_breakable
import server

DEFAULT_PORT = 1888
FONT_FILE = 'neoletters.ttf'
FONT_NAME = 'Neoletters'
BOARD_SCALE = 2

RES = dict()
POLL = 0.0001
CELL_SIZE = 16

GRID = pyglet.image.TextureGrid(
    pyglet.image.ImageGrid(pyglet.resource.image('img/sprites.png'),
                           rows=8,
                           columns=16)
)

SPRITES = {
    'a_front': slice((7, 0), (8, 4)),
    'a_left': slice((7, 4), (8, 8)),
    'a_right': slice((7, 8), (8, 12)),
    'a_back': slice((7, 12), (8, 16)),
    'b_front': slice((6, 0), (7, 4)),
    'b_left': slice((6, 4), (7, 8)),
    'b_right': slice((6, 8), (7, 12)),
    'b_back': slice((6, 12), (7, 16)),
    'c_front': slice((5, 0), (6, 4)),
    'c_left': slice((5, 4), (6, 8)),
    'c_right': slice((5, 8), (6, 12)),
    'c_back': slice((5, 12), (6, 16)),
    'd_front': slice((4, 0), (5, 4)),
    'd_left': slice((4, 4), (5, 8)),
    'd_right': slice((4, 8), (5, 12)),
    'd_back': slice((4, 12), (5, 16)),
    'avatar_a': (7, 0),
    'avatar_b': (6, 0),
    'avatar_c': (5, 0),
    'avatar_d': (4, 0),
    'bomb': (3, 3),
    'wall': (3, 8),
    'wall_b': (3, 9),
    'floor': (3, 10),
    'flame_c': (3, 0),
    'flame_v': (3, 1),
    'flame_h': (3, 2),
    'flame_w': (3, 11),
    'cross': (3, 12),
    'flame': (3, 13),
    'ok': (3, 14),
    'no': (3, 15),
    '~': (3, 4),
    '+': (3, 5),
    '!': (3, 6),
}


class PixSprite(pyglet.sprite.Sprite):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        glTexParameteri(self._texture.target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(self._texture.target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)


def sprite(coords: Coords, res_name, batch=None, scale=None, idx=None):
    x, y = coords
    tex = GRID[SPRITES[res_name]]

    if idx is not None:
        tex = tex[idx]

    sp = PixSprite(
        tex,
        x=x, y=y,
        batch=batch,
    )
    if scale:
        sp.scale = scale
    return sp


def label(coords: Coords, text: str, **kw):
    x, y = coords
    return pyglet.text.Label(
        x=x, y=y, text=text, font_name=FONT_NAME, **kw)


class GameView:
    def __init__(self, offset_x, offset_y):
        self.walls = pyglet.graphics.Batch()
        self.players = pyglet.graphics.Batch()
        self.effects = pyglet.graphics.Batch()
        self.off_x, self.off_y, = offset_x, offset_y
        self.death_timers = {}
        self.force_update = 0

    def update_all(self, gs: GameState):
        self.update_walls(gs)
        self.update_players(gs)
        self.update_bombs(gs)
        self.update_flames(gs)
        self.update_bonuses(gs)

    def update_walls(self, gs: GameState):
        self._walls = [
            sprite(gs.cell_coords(gs.cell_from_idx(i)),
                   'wall_b' if is_breakable(v) else 'wall',
                   self.walls)
            for i, v in enumerate(gs.cells)
            if is_wall(v)
        ]
        self._walls += [
            sprite(gs.cell_coords(gs.cell_from_idx(i)),
                   'floor',
                   self.walls)
            for i, v in enumerate(gs.cells)
            if not is_wall(v)
        ]

    def update_bonuses(self, gs):
        self._bonuses = [
            sprite(c.pos, c.kind, self.effects)
            for c in gs.collectibles
        ]

    def update_flames(self, gs: GameState):
        self._flames = [
            sprite(f.pos, f'flame_{f.kind}', self.effects)
            for f in gs.flames
        ]

    def update_players(self, gs: GameState):
        def _sprite(p):
            direction = Direction(p.direction)
            if Direction.DOWN in direction:
                d = 'front'
            elif Direction.LEFT in direction:
                d = 'left'
            elif Direction.RIGHT in direction:
                d = 'right'
            elif Direction.UP in direction:
                d = 'back'

            res = f"{p.pid}_{d}"

            start_time = p.moving_time and 1+p.moving_time
            idx = int(start_time / 0.2 % 4)
            return sprite(p.pos, res, self.players, idx=idx)

        now = time.time()
        self._players = []

        for name, p in gs.players.items():
            if name not in self.death_timers and not p.alive:
                self.death_timers[name] = now
                self.force_update = now + 2

            if ((name not in self.death_timers)
                    or (now - self.death_timers[name] < 2)):
                self._players.append(_sprite(p))

    def update_bombs(self, gs: GameState):
        self._bombs = [
            sprite(b.pos, 'bomb', self.players)
            for b in gs.bombs
        ]

    def draw(self):
        pyglet.gl.glPushMatrix()
        pyglet.gl.glTranslatef(self.off_x, self.off_y, 0)
        pyglet.gl.glScalef(BOARD_SCALE, BOARD_SCALE, BOARD_SCALE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)  # noqa
        self.walls.draw()
        self.effects.draw()
        self.players.draw()
        pyglet.gl.glPopMatrix()


def player_hud(pname, player, x, y, anchor_x, anchor_y):
    avatar_x = x + 5 if anchor_x == 'left' else x - 70
    label_x = x + 80 if anchor_x == 'left' else x - 80
    bomb_x = label_x if anchor_x == 'left' else label_x - 95
    bonus_x = bomb_x if anchor_x == 'left' else avatar_x - 20

    avatar_y = y - 70 if anchor_y == 'top' else y + 2
    label_y = y-5 if anchor_y == 'top' else y + 52
    bomb_y = y - 45 if anchor_y == 'top' else y + 25
    bonus_y = bomb_y - 20

    avatar = sprite((avatar_x, avatar_y), f"avatar_{player.pid}", scale=4)
    extra = [sprite((avatar_x, avatar_y), 'cross', scale=4)] \
        if not player.alive else []
    color = (192, 192, 192, 255)
    name = label((label_x, label_y),
                 pname,
                 anchor_x=anchor_x,
                 anchor_y=anchor_y,
                 font_size=15,
                 color=color)

    items = [sprite((bomb_x, bomb_y), 'bomb'),
             label((bomb_x + 20, bomb_y+2),
                   f'x{player.bomb_limit}',
                   font_size=10,
                   color=color)]
    items += [sprite((bomb_x + 55, bomb_y), 'flame'),
              label((bomb_x + 75, bomb_y+2),
                    f'x{player.bomb_radius}',
                    font_size=10,
                    color=color)]

    if player.speed_boots:
        items += [sprite((bonus_x, bonus_y), '~')]

    return [name, avatar, *(extra+items)]


class HUD:
    def __init__(self, window):
        self.window = window
        self.player_anchors = [
            (5, window.height - 5, 'left', 'top'),
            (window.width-5, window.height-5, 'right', 'top'),
            (5, 5, 'left', 'bottom'),
            (window.width-5, 5, 'right', 'bottom'),
        ]

    def update(self, gs: GameState):
        self._players = []
        for i, (pname, p) in enumerate(gs.players.items()):
            self._players += player_hud(
                pname, p,
                x=self.player_anchors[i][0],
                y=self.player_anchors[i][1],
                anchor_x=self.player_anchors[i][2],
                anchor_y=self.player_anchors[i][3],
            )

    def draw(self):
        H = 85
        w, h = self.window.width, H
        bgs = [(0, self.window.height)]
        if len(self._players) > 2:
            bgs.append((0, H))
        for x, y in bgs:
            pyglet.graphics.draw(
                4, pyglet.gl.GL_QUADS,
                ('v2i', (x, y, x+w, y, x+w, y-h, x, y-h)),
                ('c4B', (20,20,20, 255)*4),
            )
        for e in self._players:
            e.draw()


class GameScreen:
    def __init__(self, window, gs: GameState):
        self.hud = HUD(window)
        self.hud.update(gs)

        ox = (window.width / 2) - (CELL_SIZE * gs.width * BOARD_SCALE / 2)
        oy = (window.height / 2) - (CELL_SIZE * gs.height * BOARD_SCALE / 2)
        self.gv = GameView(ox, oy)
        self.gv.update_all(gs)

    def draw(self):
        self.gv.draw()
        self.hud.draw()

    @property
    def force_update(self):
        return self.gv.force_update

    def update(self, update, gs, force=False):
        """ Update screen elements based on the state update received """
        self.hud.update(gs)  # anyway
        if force or 'players' in update:
            self.gv.update_players(gs)
        if force or 'bombs' in update:
            self.gv.update_bombs(gs)
        if force or 'flames' in update:
            self.gv.update_flames(gs)
        if force or 'collectibles' in update:
            self.gv.update_bonuses(gs)
        if force or 'cells' in update:
            self.gv.update_walls(gs)


def prompt_screen():
    # TODO will do last, arguments for now
    name_lbl = pyglet.text.Label('Name:')
    return [name_lbl]


class LobbyView:
    _statuses = []

    def __init__(self, x, y):
        self._labels = []
        self.x, self.y = x, y
        self.ui = None
        self.info = label(
            (x-140, y + 65),
            "Waiting for everyone to press Enter...",
            font_size=15,
            color=(128, 128, 128, 255)
        )

    def update(self, players):
        data = [(i, d) for i, d in enumerate(players.items())]
        self.ui = pyglet.graphics.Batch()
        self._labels = [
            label((self.x, self.y - i*25), n, batch=self.ui)
            for i, (n, v) in data
        ]
        self._statuses = [
            sprite((self.x - 24, self.y - 3 - i*25), 'ok' if v else 'no',
                   batch=self.ui)
            for i, (n, v) in data
        ]

    def draw(self):
        if not self.ui:
            return
        self.ui.draw()
        self.info.draw()


class Prompt:
    def __init__(self, x, y, width):
        self.document = pyglet.text.document.UnformattedDocument()
        self.document.set_style(0, len(self.document.text),
                                {'color': (255, 255, 255, 255)})
        font = self.document.get_font()
        height = font.ascent - font.descent
        self.label = label((x, y), "Enter name[@server]:")
        self.layout = pyglet.text.layout.IncrementalTextLayout(
            self.document, width, 25)
        self.layout.x = x
        self.layout.y = y - 35
        self.caret = pyglet.text.caret.Caret(self.layout,
                                             color=(255, 255, 255))

    def draw(self):
        self.label.draw()
        self.layout.draw()


class Client:
    def __init__(self, window):
        self.loop = asyncio.get_event_loop()
        self.keys = key.KeyStateHandler()
        window.push_handlers(self.keys)
        self.pname = 'NoName'
        self._moving = False
        self.window = window
        self.ready = False
        self.home = True
        self.transport = None
        self.connected = False
        self.ingame = False
        self.status_label = label(
            (10, 10), "",
            anchor_y='bottom'
        )
        self._message = None
        self.lobby_view = LobbyView(window.width / 2 - 70,
                                    window.height - 300)
        self.logo = pyglet.sprite.Sprite(
            RES['logo'],
            x=self.window.width/2 - 140,
            y=self.window.height - 160,
        )
        self.logo.scale = 2

        self.prompt = Prompt(window.width/2 - 125, 100, 250)
        window.push_handlers(self.prompt.caret)

    def fake_state(self):
        from bomb import load_level, Player
        self.game = GameState()
        self.game.set_level(*load_level('map1.txt'))
        self.connected = True
        self.ingame = True
        self.message = None
        self.game.running = True
        self.game.players = {
            'Freddy': Player((0, 0), 'a', bomb_limit=5),
            'Sarah': Player((0, 0), 'b', bomb_limit=19, speed_boots=True),
            'Jean-Jacques': Player((0, 0), 'c', speed_boots=True),
            'Boboss': Player((0, 0), 'd', bomb_limit=3),
        }
        self.game_view = GameScreen(self.window, self.game)

    def __call__(self):
        return self

    def connection_made(self, transport):
        self.transport = transport
        self.send({'code': 'hi', 'name': self.pname})

    def datagram_received(self, data, addr):
        data = json.loads(data.decode())
        code = data['code']
        if code == 'welcome':
            self.connected = True
            self.message = None
        elif code == 'ping':
            self.send(data)  # send back
        elif code == 'lobby':
            self.lobby_view.update(data['players'])
        elif code == 'fatal':
            self.message = data['text']
        elif code == 'update':
            state = data['state']
            self.game.load(state)
            self.game_view.update(state, self.game)
        elif code == 'pid':  # propably useless, will see
            self.pid = data['pid']
        elif code == 'game_start':
            self.game = GameState()
            self.game.load(data['state'])
            self.game_view = GameScreen(self.window, self.game)
            self.ingame = True
            print(data)

    def error_received(self, error):
        self.status_label.text = str(error)

    def update(self, dt):
        if not self.ingame:
            return

        now = time.time()
        if now < self.game_view.force_update:
            self.game_view.update({}, self.game, True)

        d = Direction(0)
        if self.keys[key.UP]:
            d |= Direction.UP
        if self.keys[key.LEFT]:
            d |= Direction.LEFT
        if self.keys[key.DOWN]:
            d |= Direction.DOWN
        if self.keys[key.RIGHT]:
            d |= Direction.RIGHT
        if d:
            self._moving = True
            self.send({'code': 'move', 'dir': d.value})
        elif self._moving:
            self._moving = False
            self.send({'code': 'stop'})

    def send(self, payload):
        try:
            self.transport.sendto(json.dumps(payload).encode())
        except AttributeError:
            pass

    async def terminate(self):
        self.send({'code': 'bye'})
        await asyncio.sleep(0.2)

    @property
    def in_lobby(self):
        return self.connected and not self.ingame

    def go(self):
        self.home = False
        text = self.prompt.document.text.strip()
        name, *text = text.split('@')
        self.pname = name

        if text:
            host = text[0]
            self.message = f"Connecting to {host}"
        else:
            self.message = "Creating server..."
            self.loop.create_task(server.endpoint(self.loop))
            host = '127.0.0.1'

        async def connect():
            await asyncio.sleep(1)
            await self._client((host, DEFAULT_PORT))

        self.loop.create_task(connect())

    def on_key_press(self, sym, mod):
        if self.home:
            if sym == key.ENTER:
                self.go()
        elif self.in_lobby:
            if sym == key.ENTER:
                self.ready = not self.ready
                self.send({'code': 'ready',
                           'ready': self.ready})
        elif self.ingame:
            if sym == key.SPACE:
                self.send({'code': 'drop_bomb'})

    def draw(self):
        if self.ingame:
            self.game_view.draw()
            if not self.game.running:
                w, h = self.window.width, self.window.height
                pyglet.graphics.draw(
                    4, pyglet.gl.GL_QUADS,
                    ('v2i', (0, 0, w, 0, w, h, 0, h)),
                    ('c4B', (50, 50, 50, 128)*4),
                )

        elif self.connected:
            self.lobby_view.draw()

        elif self.home:
            self.prompt.draw()

        if not self.ingame:
            self.logo.draw()

        if self.message:
            pad = 10
            w = self.status_label.content_width + pad*2
            h = self.status_label.content_height + pad*2
            x = (self.window.width - w) // 2
            y = (self.window.height - h) // 2
            self.status_label.x = x
            self.status_label.y = y
            x, y = x - pad, y - pad
            pyglet.gl.glLineWidth(2)
            pyglet.graphics.draw(
                4, pyglet.gl.GL_QUADS,
                ('v2i', (x, y, x+w, y, x+w, y+h, x, y+h)),
                ('c3B', (50, 50, 50)*4),
            )
            pyglet.graphics.draw(
                4, pyglet.gl.GL_LINE_LOOP,
                ('v2i', (x, y, x+w, y, x+w, y+h, x, y+h)),
                ('c3B', (200, 0, 0)*4),
            )
            self.status_label.draw()

    async def _client(self, host):
        transport, _ = await self.loop.create_datagram_endpoint(
            self, remote_addr=host)

    @property
    def message(self):
        return self._message

    @message.setter
    def message(self, msg):
        self._message = msg
        if msg is not None:
            self.status_label.text = msg


def start():
    loop = asyncio.get_event_loop()
    window = pyglet.window.Window(
        width=600,
        height=600,
    )

    pyglet.font.add_file(FONT_FILE)

    RES.update({
        'logo': pyglet.resource.image('img/logo.png'),
        'hud': pyglet.resource.image('img/player_hud.png'),
    })

    glEnable(GL_BLEND)  # noqa
    #glClearColor(42/255, 29/255, 13/255, 1)  # noqa
    glClearColor(0, 0, 0, 1)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)  # noqa
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)  # noqa
    client = Client(window)

    async def pyglet_loop():
        while True:
            pyglet.clock.tick()
            if window.has_exit:
                break
            window.dispatch_events()
            window.dispatch_event('on_draw')
            window.flip()
            await asyncio.sleep(POLL)
        await client.terminate()
        loop.stop()

    @window.event
    def on_draw():
        window.clear()
        client.draw()

    window.push_handlers(client.on_key_press)
    loop.create_task(pyglet_loop())

    pyglet.clock.schedule(client.update)

    loop.run_forever()


def main():
    start()


if __name__ == "__main__":
    main()
