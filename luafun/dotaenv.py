"""This module encapsulate the basic Dota2Game API and make it a RL gym environment
that is suitable for machine learning
"""
import asyncio
from itertools import chain
import logging
import time
import traceback

import torch


from luafun.game.game import Dota2Game
from luafun.game.modes import DOTA_GameMode
import luafun.game.dota2.state_types as msg
from luafun.game.ipc_send import TEAM_RADIANT, TEAM_DIRE
from luafun.game.action import action_space
import luafun.game.constants as const
import luafun.game.action as actions
from luafun.utils.options import option
from luafun.observation.stitcher import Stitcher
from luafun.reward import Reward
from luafun.draft import DraftTracker


log = logging.getLogger(__name__)


def team_name(faction):
    if faction == TEAM_RADIANT:
        return 'Radiant'
    return 'Dire'


async def _acquire_faction(state):
    # wait for latest diff to be applied
    async with state._lock:
        state._r += 1
        return state.copy()


def acquire_state(state):
    return asyncio.run(_acquire_faction(state))


# TODO: add while env.drafting()
# TODO: add while env.playing()
# => add waiting for game phase see DOTA_GameState
class Dota2Env(Dota2Game):
    """Dota2 Game Environment

    .. image:: ../_static/env_diagram.png


    Notes
    -----
    if you installed dota in a custom location you can set the environment variable ``LUAFUN_DOTA_PATH``
    to make the environment pick it up automatically

    .. code-block:: bash

        export LUAFUN_DOTA_PATH=/media/setepenre/local/SteamLibraryLinux/steamapps/common/dota2/


    Parameters
    ----------
    path: str
        Path to the game folder ``.../dota2``

    dedicated: bool
        runs server only

    stitcher: Stitcher
        Stitch game state together

    reward: Reward
        Used to compute reward after every step

    _config:
        Internal argument used when the HTTP server controls the environment
    """
    def __init__(self, path=option('dota.path', None), dedicated=True, draft=0, stitcher=None, reward=None, _config=None):
        super(Dota2Env, self).__init__(path, dedicated, draft, config=_config)
        # For debugging only
        # self.radiant_message = open(self.paths.bot_file('out_radiant.txt'), 'w')
        # self.dire_message = open(self.paths.bot_file('out_dire.txt'), 'w')

        self._action_space = action_space()

        # Function to stich state together
        if stitcher is None:
            stitcher = Stitcher

        self.sticher_factory = stitcher
        self.dire_stitcher = stitcher(faction=TEAM_DIRE)
        self.radiant_stitcher = stitcher(faction=TEAM_RADIANT)

        # Reward function
        if reward is None:
            reward = Reward()

        self.reward = reward

        # Draft tracker for the drafting AI
        self.draft_tracker = DraftTracker()
        self.radiant_stitcher.draft = self.draft_tracker.draft
        self.dire_stitcher.draft = self.draft_tracker.draft

        self.has_next = 0
        self.step_start = None
        self.step_end = 0
        self.cnt = 0
        self.avg = 0

        # self.unit_size = open('unit_size.txt', 'w')

    def new_draft_state(self, ds):
        """Called every time a picks / ban is made"""
        self.draft_tracker.update(ds)

    def end_draft(self, ds):
        """Called every time a picks / ban is made"""
        self.draft_tracker.end_draft(ds)

    def cleanup(self):
        # self.radiant_message.close()
        # self.dire_message.close()
        # self.unit_size.close()
        pass

    def dire_message(self):
        return self.dire_stitcher.latest_message

    def radiant_message(self):
        return self.radiant_stitcher.latest_message

    # For states we should have a queue of state to observe
    def update_dire_state(self, message: msg.CMsgBotWorldState):
        """Receive a state diff from the game for dire"""
        try:
            self.dire_stitcher.apply_diff(message)
            self.has_next += 1
        except Exception as e:
            log.error(f'Error happened during state stitching {e}')
            log.error(traceback.format_exc())

        # self.unit_size.write(f'{len(self._dire_state._units)}\n')

        # self.dire_message.write(str(type(message)) + '\n')
        # self.dire_message.write(str(message))
        # self.dire_message.write('-------\n')

    def update_radiant_state(self, message: msg.CMsgBotWorldState):
        """Receive a state diff from the game for radiant"""
        try:
            self.radiant_stitcher.apply_diff(message)
            self.has_next += 1
        except Exception as e:
            log.error(f'Error happened during state stitching {e}')
            log.error(traceback.format_exc())

        # self.radiant_message.write(str(type(message)) + '\n')
        # self.radiant_message.write(str(message))
        # self.radiant_message.write('-------\n')

    def receive_message(self, faction: int, player_id: int, message: dict):
        """We only use log to get errors back if any"""
        pass

    # Gym Environment API
    # -------------------
    def render(self):
        """Enable game rendering"""
        self.options.dedicated = False

    def reset(self):
        """Stop the game if running and start a new game

        Returns
        -------
        observation: Tuple[FactionState, FactionState]
            state observation (radiant, dire)
        """
        if self.running:
            self.__exit__(None, None, None)
            self.radiant_stitcher = self.sticher_factory()
            self.dire_stitcher = self.sticher_factory()

        self.__enter__()
        return self.radiant_stitcher, self.dire_stitcher

    def close(self):
        """Stop the game"""
        self.__exit__(None, None, None)

    @property
    def action_space(self):
        """Returns a gym.Space object which we can use to sample action from

        Notes
        -----

        .. code-block:: python

            {
                'Radiant': {
                    # Player 1
                    '0': {
                        action       = One of 25 base actions
                        vloc         = Location Vector x, y
                        hUnit        = Unit handle
                        abilities    = Ability/Item slot to use (40)
                        tree         = Tree ID
                        runes        = Rune ID
                        items        = Which item to buy
                        ix2          = Inventory Item slot for swapping
                    },
                    # Player 2
                    '1' : {
                        ...
                    },

                    ...

                    # Hero Selection command
                    'HS'            = {
                        select = spaces.Discrete(const.HERO_COUNT),
                        ban    = spaces.Discrete(const.HERO_COUNT)
                    }
                }
                'Dire': [
                    ...
                ]
            }

        """
        return self._action_space

    @property
    def observation_space(self):
        """Return the observation space we observe at every step"""
        return self.dire_stitcher.observation_space

    def initial(self):
        """Return the initial state of the game"""
        return None, None, None, None

    def preprocessed_send(self, action):
        print(action)
        preprocessed = self._action_preprocessor(action)

        # 1.2 Send the action
        self.send_message(preprocessed)

        return preprocessed

    def step(self, action):
        """Make an action and return the resulting state

        Returns
        -------
        observation: Tuple[FactionState, FactionState]
            state observation (radiant, dire)

        reward: float
            amount of reward that state

        done: bool
            is the game is done

        info: Optional[dict]
            returns nothing
        """
        self.step_end = time.time()
        s = time.time()
        if self.step_start:
            t = self.step_end - self.step_start
            if t > self.deadline:
                log.warning(f'took too long to take action')

            self.avg += t
            self.cnt += 1

        # 1. send action
        # 1.1 Preprocess the actions (remapping)
        if action is not None:
            preprocessed = self._action_preprocessor(action)

            # 1.2 Send the action
            self.send_message(preprocessed)

        # 2. Wait for the new stitched state
        wait_time = 0
        while self.has_next < 2 and self.running:
            try:
                self._tick()
                time.sleep(0.001)
                wait_time += 0.001
            except KeyboardInterrupt:
                return None, None, None, None

            if wait_time > 1:
                log.debug('Waiting for an unusually long time')

        self.has_next = 0
        self.perf.acquire_time += time.time() - s

        radbatch = self.radiant_stitcher.generate_batch(self.rad_bots)
        direbatch = self.dire_stitcher.generate_batch(self.dire_bots)

        obs = torch.cat((radbatch, direbatch), 0)

        rr = self.radiant_stitcher.partial_reward()
        rd = self.dire_stitcher.partial_reward()

        rr = rr - rd
        rd = - rr

        rr = torch.ones(radbatch.shape[0]) * rr
        dd = torch.ones(direbatch.shape[0]) * rd

        reward = torch.cat([rr, dd], 0)

        # 3. Compute the reward
        # reward = self.reward(obs[:len(self.rad_bots)], obs[len(self.rad_bots):])
        done = self.state.get('win', None) is not None
        info = dict()

        self.step_start = time.time()
        return obs, reward, done, info

    # Helpers
    # -------
    def _action_preprocessor(self, message):
        players = chain(message[TEAM_RADIANT].items(), message[TEAM_DIRE].items())

        for pid, action in players:
            if pid == 'HS' and action[actions.DraftAction.EnableDraft] == 1:
                # find the name of the hero from its ID
                hid = action[actions.DraftAction.SelectHero]
                shero = const.HEROES[hid]['name']
                action[actions.DraftAction.SelectHero] = shero

                hid = action[actions.DraftAction.SelectHero]
                shero = const.HEROES[action[hid]]['name']
                action[actions.DraftAction.BanHero] = shero
                continue

            if len(action) == 0:
                continue

            # slots needs to be remapped from our unified slot
            # to the game internal slot
            hid = self.heroes[pid]['hid']
            slot = action[actions.ARG.nSlot]
            slot = const.HERO_LOOKUP.ability_from_id(hid, slot)
            action[actions.ARG.nSlot] = slot

            # Remap Item Name
            nitem = action[actions.ARG.sItem]
            sitem = const.ITEMS[nitem]['name']
            action[actions.ARG.sItem] = sitem

            # Remap vloc to be across the map
            pos = action[actions.ARG.vLoc]

            # print(action)
            x = pos[0] * 8288
            y = pos[1] * 8288
            action[actions.ARG.vLoc] = (x, y)

            state = self.radiant_stitcher
            if pid >= 5:
                state = self.dire_stitcher

            unit, rune, tree = state.get_entities(x, y)

            action[actions.ARG.iTree] = tree
            action[actions.ARG.nRune] = rune
            action[actions.ARG.hUnit] = unit

        return message


def _default_game(path=None, dedicated=True, config=None):
    game = Dota2Env(path, dedicated=dedicated, _config=config)
    game.options.ticks_per_observation = 4
    game.options.host_timescale = 2
    return game


def mid1v1(path=None, config=None):
    game = _default_game(path, config=config)
    game.options.game_mode = int(DOTA_GameMode.DOTA_GAMEMODE_1V1MID)
    return game


def allpick_nobans(path=None, config=None):
    game = _default_game(path, config=config)
    game.options.game_mode = int(DOTA_GameMode.DOTA_GAMEMODE_AP)
    return game


def ranked_allpick(path=None, config=None):
    game = _default_game(path, config=config)
    game.options.game_mode = int(DOTA_GameMode.DOTA_GAMEMODE_ALL_DRAFT)
    return game


def captains_mode(path=None, config=None):
    """Tournament mode with a captain drafting for the whole team"""
    game = _default_game(path, config=config)
    game.options.game_mode = int(DOTA_GameMode.DOTA_GAMEMODE_CM)
    return game


def captains_draft(path=None, config=None):
    """Similar to captains mode with a 27 heroes, only 3 bans per teams"""
    game = _default_game(path, config=config)
    game.options.game_mode = int(DOTA_GameMode.DOTA_GAMEMODE_CD)
    return game


def allrandom(path=None, config=None):
    game = _default_game(path, config=config)
    game.options.game_mode = int(DOTA_GameMode.DOTA_GAMEMODE_AR)
    return game


_environments = {
    'mid1v1': mid1v1,
    'allpick_nobans': allpick_nobans,
    'ranked_allpick': ranked_allpick,
    'allrandom': allrandom,
    'captains_draft': captains_draft,
    'captains_mode': captains_mode
}


def dota2_environment(name, *args, **kwargs) -> Dota2Env:
    """Returns pre configured dota2 environment for convenience"""
    factory = _environments.get(name)

    if factory:
        return factory(*args, **kwargs)

    return None
