from collections import defaultdict
from dataclasses import dataclass, field
import logging
import os
import multiprocessing as mp
import subprocess
import time

from luafun.game.modes import DOTA_GameMode
from luafun.game.config import DotaPaths
from luafun.game.args import DotaOptions
from luafun.game.inspect import http_inspect
from luafun.game.ipc_recv import ipc_recv
from luafun.game.ipc_send import ipc_send, TEAM_RADIANT, TEAM_DIRE, new_ipc_message
import luafun.game.dota2.state_types as msg
from luafun.game.extractor import Extractor, SaveReplay
import luafun.game.constants as const
from luafun.game.states import world_listener_process
from luafun.utils.options import option
from luafun.game.performance import ProcessingStates


log = logging.getLogger(__name__)


@dataclass
class WorldConnectionStats:
    message_size: int = 0
    success: int = 0
    error: int = 0
    reconnect: int = 0
    double_read: int = 0


@dataclass
class Stats:
    radiant: WorldConnectionStats = field(default_factory=WorldConnectionStats)
    dire: WorldConnectionStats = field(default_factory=WorldConnectionStats)


SECONDS_PER_TICK = 1 / 30

TEAM_NAMES = {
    TEAM_RADIANT: 'Radiant',
    str(TEAM_RADIANT): 'Radiant',
    TEAM_DIRE: 'Dire',
    str(TEAM_DIRE): 'Dire',
}


def team_name(v):
    return str(TEAM_NAMES.get(v))


class StateHolder:
    def __init__(self):
        self.value = 0


class Dota2Game:
    """Simple interface to listen and send messages to a running dota2 game instance
    This class only stich the different components together to provide a unified API over them
    You should subclass this to implement the desired behaviour
    No ML related feature there

    Components
    ----------

    * world state listenner: receive state update about dire/radiant from the game itself
    * ipc_recv: receive message from each bot (through the console log)
    * ipc_send: send message to each bot (through a generated lua file)
    * http server: used to inspect the game in realitime

    6 Processes are created when launching the environment

    .. code-block::

        1) Main Process             : 29824 | 1% CPU | stich state together
        2) WorldListener-Dire       : 26272 | 4% CPU | retrieve game state
        3) WorldListener-Radiant    : 33228 | 4% CPU | retrieve game state
        4) IPC-recv                 : 28848 | 0% CPU | Read Game logs for bot errors
        5) HTTP-server              : 30424 | 0% CPU | Debug Process
        6) Multiprocess Manager

    Notes
    -----
    Type  ``jointeam spec`` in the dota2 console to observe the game

    We use multiprocess, asyncio was not given the required performance.
    A huge part of performance is used to receive messages from the game itself
    """
    def __init__(self, path=option('dota.path', None), dedicated=True, draft=0, config=None):
        self.paths = DotaPaths(path)
        self.options = DotaOptions(dedicated=dedicated, draft=draft)
        self.args = None

        self.process = None
        self.reply_count = defaultdict(int)

        self.manager = None
        self.state = None

        self.dire_state_process = None
        self.radiant_state_process = None

        self.dire_state_delta_queue = None
        self.radiant_state_delta_queue = None

        self.ipc_recv_process = None
        self.ipc_recv_queue = None

        self.config = config
        self.http_server = None
        self.http_rpc_send = None
        self.http_rpc_recv = None

        self.heroes = None
        self.uid = StateHolder()
        self.ready = False
        self.pending_ready = True
        self.bot_count = 10
        self.stats = Stats()
        self.players = {
            TEAM_RADIANT: 0,
            TEAM_DIRE: 0
        }

        self.dire_bots = []
        self.rad_bots = []

        self.dire_perf = None
        self.rad_perf = None
        self.dire_perf_prev = None
        self.rad_perf_prev = None
        self.perf = ProcessingStates(0, 0, 0, 0, 0, 0, 0, 0)

        self.extractor = Extractor()
        self.replay = SaveReplay('replay.txt')
        log.debug(f'Main Process: {os.getpid()}')
        self._bots = []

        # IPC config to configure bots
        self.ipc_config = {
            'draft_start_wait': 10,
            'draft_pick_wait': 1,
        }
        ipc_send(self.paths.ipc_config_handle, self.ipc_config, StateHolder())

    def performance_counters(self):
        return self.perf

    @property
    def batch_size(self):
        """A single dota2 environment generates a batch of observations (10 if all players are controlled by bots)"""
        return len(self._bots)

    @property
    def bot_ids(self):
        """Returns the list of player id that are controlled by bots"""
        return self._bots

    @property
    def deadline(self):
        """Return the inference time limit in seconds.
        i.e it is the time remaining before receiving a new observation
        """
        return SECONDS_PER_TICK * self.options.ticks_per_observation / self.options.host_timescale

    @property
    def running(self):
        """Returns true if the game is running"""
        return self.state and self.state.get('running', False)

    def is_game_ready(self):
        """Returns true if all bots sent us their init message"""
        return len(self._bots) >= self.bot_count

    def launch_dota(self):
        """Launch dota game without communication processes"""
        # make sure the log is empty so we do not get garbage from the previous run
        try:
            if os.path.exists(self.paths.ipc_recv_handle):
                os.remove(self.paths.ipc_recv_handle)
        except Exception as e:
            log.error(f'Error when removing file {e}')

        try:
            if os.path.exists(self.paths.ipc_send_handle):
                os.remove(self.paths.ipc_send_handle)
        except Exception as e:
            log.error(f'Error when removing file {e}')

        from sys import platform

        path = [self.paths.executable_path]
        if platform == "linux" or platform == "linux2":
           path = ['/home/setepenre/.steam/ubuntu12_32/steam-runtime/run.sh', self.paths.executable_path]

        # save the arguments of the current game for visibility
        self.args = path + self.options.args(self.paths)
        print(' '.join(self.args))
        self.process = subprocess.Popen(
            self.args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
            # , stdin=subprocess.PIPE
        )

    def _get_next(self, q1, q2):
        m1, m2 = None, None

        while self.running:
            if m1 is None and not q1.empty():
                m1 = q1.get()

                self.rad_perf = m1['perf']
                self.rad_perf.state_rcv = time.time()

            if m2 is None and not q2.empty():
                m2 = q2.get()

                self.dire_perf = m2['perf']
                self.dire_perf.state_rcv = time.time()

            if m1 and m2:
                break

        n1 = q1.qsize()
        n2 = q2.qsize()

        if any((n1 > 2, n2 > 2)):
            log.warning(f'Running late on state processing (radiant: {n1}) (dire: {n2})')

        return m1, m2

    def start_ipc(self):
        """Start inter-process communication processes.
        i.e launch all subsystems that enable us to talk to the running game
        """
        self.manager = mp.Manager()

        if self.config is None:
            self.state = self.manager.dict()
            self.state['running'] = True
        else:
            self.state = self.config.state

        level = logging.DEBUG

        # Dire State
        self.dire_state_delta_queue = self.manager.Queue()
        self.dire_state_process = world_listener_process(
            '127.0.0.1',
            self.options.port_dire,
            self.dire_state_delta_queue,
            self.state,
            None,
            'Dire',
            level
        )

        # Radiant State
        self.radiant_state_delta_queue = self.manager.Queue()
        self.radiant_state_process = world_listener_process(
            '127.0.0.1',
            self.options.port_radiant,
            self.radiant_state_delta_queue,
            self.state,
            None,
            'Radiant',
            level
        )

        # IPC receive
        self.ipc_recv_queue = self.manager.Queue()
        self.ipc_recv_process = ipc_recv(
            self.paths.ipc_recv_handle,
            self.ipc_recv_queue,
            self.state,
            level
        )

        # Setup the server as an environment inspector
        if self.config is None:
            self.http_rpc_recv = self.manager.Queue()
            self.http_rpc_send = self.manager.Queue()
            self.http_server = http_inspect(
                self.state,
                self.http_rpc_send,
                self.http_rpc_recv,
                level
            )
        else:
            # Setup the server as a monitor
            self.http_rpc_recv = self.config.rpc_recv
            self.http_rpc_send = self.config.rpc_send

    def stop(self, timeout=2):
        """Stop the game in progress

        Notes
        -----
        On windows the dota2 game is not stopped but the underlying python processes are
        """
        self.state['running'] = False

        # wait the game to finish before exiting
        total = 0
        while self.process.poll() is None and total < timeout and self.process.returncode is None:
            time.sleep(0.01)
            total += 0.01

        if total < timeout:
            log.debug('Process was not terminating forcing close')

        if self.process.poll() is None:
            self.process.terminate()

        if self.extractor:
            self.extractor.close()

        if self.replay:
            self.replay.close()

    def _handle_http_rpc(self):
        # handle debug HTTP request
        if self.http_rpc_recv.empty():
            return

        msg = self.http_rpc_recv.get()
        if not isinstance(msg, dict):
            self.http_rpc_send.put(dict(error=msg))
            return

        attr = msg.get('attr')
        args = msg.get('args', [])
        kwargs = msg.get('kwargs', dict())

        result = dict(error=f'Object does not have attribute {attr}')

        if hasattr(self, attr):
            result = getattr(self, attr)(*args, **kwargs)

        if result is None:
            result = dict(msg='none')

        self.http_rpc_send.put(result)

    def _handle_ipc(self):
        if self.ipc_recv_queue.empty():
            return

        msg = self.ipc_recv_queue.get()
        self._receive_message(*msg)

    def _handle_state(self):
        s = time.time()
        radiant, dire = self._get_next(
            self.radiant_state_delta_queue,
            self.dire_state_delta_queue
        )

        if radiant is None or dire is None:
            return

        self.replay.save(radiant, dire)

        self.update_dire_state(dire)
        self.dire_perf.state_applied = time.time()

        self.update_radiant_state(radiant)
        self.rad_perf.state_applied = time.time()

        e = time.time()
        self.state['state_time'] = e - s

    def _tick(self):
        stop = False

        # Process event
        if not self.running:
            self.stop()
            stop = True

        winner = self.state.get('win', None)
        if winner is not None:
            log.debug(f'{winner} won')
            self.stop()
            stop = True
        # ---

        s = time.time()
        self._handle_http_rpc()
        e = time.time()
        self.state['http_time'] = e - s

        s = time.time()
        self._handle_ipc()
        e = time.time()
        self.state['ipc_time'] = e - s

        self._handle_state()

        if self.pending_ready and self.ready:
            self.pending_ready = False
            # I wish something like this was possible
            # out, err = self.process.communicate(b'jointeam spec')
            # log.debug(f'{out} {err}')

        return stop

    def wait_end_setup(self):
        """Wait until draft starts"""
        while self.state and self.state.get('draft') is None and self.running:
            time.sleep(0.01)
            self._tick()

    def wait_end_draft(self):
        """Wait until draft ends and playing can start"""
        while self.state and not self.state.get('game', False) and not self.ready and self.running:
            time.sleep(0.01)
            self._tick()

    def wait(self):
        """Wait for the game to finish, this is used for debugging exclusively"""
        try:
            while self.process.poll() is None:

                time.sleep(0.01)
                stop = self._tick()

                if stop:
                    break

        except KeyboardInterrupt:
            pass

        self.stop()

    def _set_hero_info(self, info):
        """Get the game hero info"""
        self.heroes = dict()

        # Message example
        # {"P":[
        #   {"is_bot":true,"team_id":2,"hero":"npc_dota_hero_antimage","id":0},
        #   {"is_bot":true,"team_id":2,"hero":"npc_dota_hero_axe","id":1},
        #   {"is_bot":true,"team_id":2,"hero":"npc_dota_hero_bane","id":2},
        #   {"is_bot":true,"team_id":2,"hero":"npc_dota_hero_bloodseeker","id":3},
        #   {"is_bot":true,"team_id":2,"hero":"npc_dota_hero_crystal_maiden","id":4},
        #   {"is_bot":true,"team_id":3,"hero":"npc_dota_hero_drow_ranger","id":5},
        #   {"is_bot":true,"team_id":3,"hero":"npc_dota_hero_earthshaker","id":6},
        #   {"is_bot":true,"team_id":3,"hero":"npc_dota_hero_juggernaut","id":7},
        #   {"is_bot":true,"team_id":3,"hero":"npc_dota_hero_mirana","id":8},
        #   {"is_bot":true,"team_id":3,"hero":"npc_dota_hero_nevermore","id":9}]
        #   }
        bot_count = 0

        for p in info:
            hero = {
                'name': p['hero'],
                'bot': p['is_bot'],
                'hid': const.HERO_LOOKUP.from_name(p['hero'])['id']
            }
            self.heroes[p['id']] = hero
            self.heroes[str(p['id'])] = hero
            bot_count += int(p['is_bot'])

        self.bot_count = bot_count

    def _set_bot_by_faction(self):
        self.dire_bots = []
        self.rad_bots = []

        for bid in self._bots:
            if bid < 5:
                self.rad_bots.append(bid)

            if bid > 4:
                self.dire_bots.append(bid)

    def _receive_message(self, faction: int, player_id: int, message: dict):
        # error processing
        error = message.get('E')
        if error is not None:
            # error message are far from critical if we were able to receive them
            log.debug(f'recv {team_name(faction)} {player_id} {error}')
            return

        # init message
        info = message.get('P')
        if info is not None:
            # the draft message can be missed
            self.state['draft'] = False

            # See who is bot or not
            if not self.heroes:
                self._set_hero_info(info)

            self._bots.append(int(player_id))
            if self.is_game_ready():
                self.state['game'] = True
                self._bots.sort()
                self._set_bot_by_faction()
                # 1v1 Mid is buggy and all bots are spawned
                # as a hack we ignore them
                if self.options.game_mode == DOTA_GameMode.DOTA_GAMEMODE_1V1MID:
                    self._bots = [0, 5]

                log.debug('All bots accounted for, Game is ready')
                self.ready = True
            return

        # Message ack
        ack = message.get('A')
        if ack is not None:
            self.reply_count[ack] += 1
            if self.reply_count[ack] == self.bot_count:
                log.debug(f'(uid: {ack}) message received by all {self.bot_count} bots')
                self.reply_count.pop(ack)
            return

        # Draft message
        ds = message.get('DS')
        if ds is not None:
            self.state['draft'] = True
            log.debug(f'received draft state')
            self.new_draft_state(ds)

        de = message.get('DE')
        if de is not None:
            self.state['draft'] = False
            log.debug(f'draft has ended')
            self.end_draft(ds)

        # Message Info
        info = message.get('I')
        if self.extractor and info is not None:
            self.extractor.save(message)

        self.receive_message(faction, player_id, message)

    def new_draft_state(self, ds):
        """Called every time a picks / ban is made"""
        pass

    def end_draft(self, ds):
        """Called every time a picks / ban is made"""
        pass

    def receive_message(self, faction: int, player_id: int, message: dict):
        """Receive a message directly from the bots"""
        print(f'{faction} {player_id} {message}')

    def update_dire_state(self, messsage: msg.CMsgBotWorldState):
        """Receive a state diff from the game for dire"""
        pass

    def update_radiant_state(self, message: msg.CMsgBotWorldState):
        """Receive a state diff from the game for radiant"""
        pass

    def send_message(self, data: dict):
        """Send a message to the bots"""
        now = time.time()
        if self.rad_perf and self.dire_perf:
            self.rad_perf.state_replied = now
            self.dire_perf.state_replied = now

            self.perf.add(self.rad_perf, self.rad_perf_prev)
            self.perf.add(self.dire_perf, self.dire_perf_prev)

        ipc_send(self.paths.ipc_send_handle, data, self.uid)

        self.dire_perf_prev = now
        self.rad_perf_prev = now

    def cleanup(self):
        """Cleanup needed by the environment"""
        pass

    def __enter__(self):
        self.launch_dota()
        self.start_ipc()
        log.debug("Game has started")
        # Create a file to say if we want to draft or not
        self.send_message(new_ipc_message(draft=self.options.draft))
        self.wait_end_setup()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.stop()

        if self.http_server is not None:
            self.http_server.terminate()

        self.dire_state_process.join()
        self.radiant_state_process.join()
        self.ipc_recv_process.join()

        self.cleanup()
        log.debug("Game has finished")
