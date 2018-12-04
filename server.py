import asyncio
import json  # TODO ujson
import time

from bomb import GameState, load_level, action, Effect

MAX_CLIENTS = 4
DEFAULT_PORT = 1888


class Server:
    # Completely arbitrary value, if too small, dt will seem too random,
    # if to big, well... less reactive.
    TICK = 1/60

    def __init__(self):
        self.started = False
        self.clients = {}
        self.ping_res = {}
        self.lobby_status = {}
        self.actions = asyncio.Queue()
        self.game = GameState()

    def __call__(self):
        return self

    def connection_made(self, transport):
        self.transport = transport
        print("Connection ready")
        self.last_time = time.time()
        loop = asyncio.get_event_loop()
        loop.create_task(self.action_loop())
        loop.create_task(self.ping_clients())

    async def action_loop(self):
        while True:
            now = time.time()
            dt = now - self.last_time

            # first, game tick, which is an action
            self.actions.put_nowait(self.game.tick)

            # then queued actions
            # better to handle all queued actions in the same tick
            pull = True
            while pull:
                try:
                    action = self.actions.get_nowait()
                except asyncio.QueueEmpty:
                    pull = False
                else:
                    effect = action(dt)
                    self.propagate(effect)
            self.last_time = time.time()
            pt = self.last_time - now
            await asyncio.sleep(self.TICK - pt)

    async def ping_clients(self):
        while True:
            now = time.time()
            for name, addr in self.clients.items():
                self.send(addr, {'code': 'ping', 't': now})

            # casting to a list as ping_res will be changed sometimes
            for name, (last_seen, ping) in list(self.ping_res.items()):
                if now - last_seen > 5:
                    print(f"Kicking inactive player {name}...")
                    self.remove_player(name)
            await asyncio.sleep(1)

    def datagram_received(self, data, addr):
        data = json.loads(data.decode())
        code = data['code']
        if code == 'hi':
            if not self.open:
                return self.send_error(addr, 'fatal',
                                       'Server is closed')
            name = data['name']
            # TODO will need to manage existing names
            print(f"New player: {name}")
            self.clients[name] = addr
            self.lobby_status[name] = False
            self.send(addr, {'code': 'welcome', 'name': name})
            self.broadcast_lobby()

        elif code == 'ping':
            name = self.get_player_name(addr)
            now = time.time()
            ping = now - data['t']
            self.ping_res[name] = now, ping
            self.broadcast({'code': 'status', 'players': self.ping_res})
        elif code == 'ready':
            name = self.get_player_name(addr)
            self.lobby_status[name] = data['ready']
            self.broadcast_lobby()
            if all(self.lobby_status.values()):
                self.start_game()
        elif code == 'bye':
            name = self.get_player_name(addr)
            print(f"Player leaving: {name}")
            self.remove_player(name)
        else:
            player = self.get_player_name(addr)
            a = action(self.game, player, data)
            if a:
                self.actions.put_nowait(a)

    @property
    def open(self):
        return len(self.clients) < MAX_CLIENTS and not self.started

    def start_game(self):
        self.started = True
        self.game.set_level(*load_level('map1.txt'))
        self.game.running = True

        for pname in self.clients:
            pid = self.game.spawn_player(pname)
            self.send(self.clients[pname],  # maybe useless
                      {'code': 'pid', 'pid': pid})

        self.broadcast({'code': 'game_start',
                        'state': self.game.dump()})

    def remove_player(self, name):
        if name not in self.clients:
            return
        self.game.remove_player(name)
        self.clients.pop(name)
        self.ping_res.pop(name)
        self.lobby_status.pop(name)
        self.broadcast_lobby()

    def get_player_name(self, addr):
        for k, v in self.clients.items():
            if v == addr:
                return k

    def propagate(self, effect: Effect):
        if effect:
            for e in effect:
                self.broadcast(e)

    def broadcast_lobby(self):
        self.broadcast({'code': 'lobby',
                        'players': self.lobby_status})

    def broadcast_state(self, *fields):
        self.broadcast({'code': 'update',
                        'state': self.game.dump(*fields)})

    def broadcast(self, payload):
        for c in self.clients.values():
            self.send(c, payload)

    def send(self, addr, payload):
        self.transport.sendto(json.dumps(payload).encode(), addr)

    def send_error(self, addr, level, text):
        self.send(addr,
                  {'code': level,
                   'text': text})


async def endpoint(loop):
    transport, protocol = await loop.create_datagram_endpoint(
        Server(), local_addr=('0.0.0.0', DEFAULT_PORT)
    )


def start_server():
    loop = asyncio.get_event_loop()

    loop.run_until_complete(
        asyncio.ensure_future(endpoint(loop), loop=loop))
    loop.run_forever()


if __name__ == '__main__':
    start_server()
