import os
import json
from enum import IntEnum

from PIL import Image
from torchvision import transforms


# Map constant
# Extracted using Lua
# might be automated so it never gets out of date


def load_source_file(name):
    dirname = os.path.dirname(__file__)
    with open(os.path.join(dirname, name), 'r') as f:
        return json.load(f)


# World Bound
BOUNDS = [
    (-8288, -8288),
    (8288, 8288)
]

ORIGIN = (8288, 8288)

RANGE = (8288, 8288)

# Game Unit
# (16576, 16576)
SIZE = (
    BOUNDS[1][0] - BOUNDS[0][0],  # x_max -  x_min
    BOUNDS[1][1] - BOUNDS[0][1],  # y_max - y_min
)


#
# Max vision comes from the Dota2 Lua API some functions are limited to this range
# Max Vision = 1600
# True max vision is 1800, 800 at night


def position_to_key(x, y, div=27):
    """Generate a position key to query entities by their position

    Examples
    --------

    Red is the collision square and black is the position with an arbitrary size.
    The position (x, y) is always inside the red square but it is not at the center.

    Our goal here is not to have an accurate collision but rather
    an efficient lookup from position with a margin of error (the red square).

    The lookup is most precise when the position is a multiple of ``div`` and least
    precise when around half of ``div``.

    .. image:: ../_static/position_mapping.png

    >>> position_to_key(-6016, -6784, 37)
    '-162-183'

    >>> position_to_key(-6016 - 14, -6784, 37)
    '-162-183'

    >>> position_to_key(-6016 + 99, -6784, 37)
    '-159-183'

    Notes
    -----
    This essentially capture anything in a ``div`` unit square.
    The unit/entity is not at the center of the square.

    Collision in dota is standardized so there is only a few sizes we need to worry about.
    We chose ``div = 27`` because it is close to the hero collision size

    This method makes the unit/tree selection a bit fuzzy, if entities are close together
    they could be mis-selected

    .. code-block:: python

        # Collision sizes
        DOTA_HULL_SIZE_BUILDING        = 298 #  Ancient
        DOTA_HULL_SIZE_TOWER 	       = 144 # Barracks
        TREES                          = 128
        DOTA_HULL_SIZE_FILLER 	       =  96 # Fillers / Outpost
        DOTA_HULL_SIZE_HUGE 	       =  80 # Power Cog
        DOTA_HULL_SIZE_HERO 	       =
         # <== Mostly Heroes
        DOTA_HULL_SIZE_REGULAR 	       =  16 # <== Melee Creep
        DOTA_HULL_SIZE_SMALL 	       =   8 # <== Range Creep
        DOTA_HULL_SIZE_SMALLEST        =   2 # Zombie

    """
    # Extract the fractional part
    # so if we are close to a frontier we cover it
    # ox = (x - int(x / div) * div)
    # oy = (y - int(y / div) * div)
    # #
    # x = x + ox / 8
    # y = y + oy / 8
    #
    # return f'{int(x / div)}{int(y / div)}'
    x = int(x / div)
    y = int(y / div)
    return f'{x}{y}'


IGNORED_TREES = dict()
DUP_TREES = dict()

topo_map = None


def load_map():
    """This is a 3.3Go image, showing heights, trees and impassable locations.
    The red channel is used for trees, green for passable and blue for heights

    Notes
    -----

    The PNG is only 873.8 kB but gets decompressed to 1Go+.
    Some application have decompression bomb safeguard that will stop decompression.

    The resulting tensor shape is torch.Size([3, 16576, 16576])

    .. image:: ../_static/topology.png

    The data was extracted from Lua using for loops with the following functions
    ``IsLocationPassable``, ``GetHeightLevel``, ``GetTreeLocation``.

    Although the image has quite a high resolution we can see that is not necessarily the case for
    the function that were called.

    Collision in Dota2 is a bit weird, Tower collision has a hull size of 288 (144 radius).
    When looking at the map we can clearly see that the radius is actually only ~259.

    .. code-block:: bash

        Blue depth means heights
        Red means tree
        Green means passable

        Blue = not passable
        Pink = Red + Blue = not passable because of trees
        Yellow = Might be passable but there is tree
        Bright Green = High ground
        Light Green = River

    """
    global topo_map

    if topo_map is not None:
        return topo_map

    dirname = os.path.dirname(__file__)
    filename = os.path.join(dirname, 'resources/gigamap.png')

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(filename)
    topo_map = transforms.ToTensor()(im)
    return topo_map


# Trees
def load_trees():
    """Load the location of all the trees

    Examples
    --------
    .. image:: ../_static/tree_minimap.png

    """
    trees = load_source_file('resources/trees.json')
    position_to_tree = dict()

    for tid, x, y, z in trees:
        tree = {
            'id': tid,
            'loc': (x, y, z)
        }

        key = position_to_key(x, y)

        if key in position_to_tree:
            x1, y1, z1 = position_to_tree[key]['loc']

            d1 = x1 * x1 + y1 * y1
            d = x * x + y * y

            # Favor trees that are closer to the origin (0, 0)
            if d < d1:
                position_to_tree[key] = tree

                DUP_TREES[key] = (x, y, z)
                IGNORED_TREES[key] = (x1, y1, z1)

            else:
                IGNORED_TREES[key] = (x, y, z)
                DUP_TREES[key] = (x1, y1, z1)

            print(f'Duplicate tree {key:>10}: [({x}, {y}, {z}), ({x1}, {y1}, {z1})]')
            continue

        position_to_tree[key] = tree

    if len(IGNORED_TREES):
        print('Total ignored trees:', len(IGNORED_TREES))
    return position_to_tree


def get_tree(x, y):
    tree_key = position_to_key(x, y)
    t = TREES.get(tree_key)
    if t:
        return t.get('id', -1)
    return -1


TREES = load_source_file('resources/trees.json')
TREE_COUNT = len(TREES)

assert TREE_COUNT == 2104


# Runes
def rune_lookup():
    runes = dict()
    all_runes = load_source_file('resources/runes.json')
    for rid, x, y, z in all_runes:
        key = position_to_key(x, y, div=100)

        if key in runes:
            print('Duplicate rune!')

        runes[key] = rid

    assert len(runes) == len(all_runes)
    return runes


def get_rune(x, y):
    key = position_to_key(x, y, div=100)
    return RUNES.get(key)


ITEMS = load_source_file('resources/items.json')
ITEM_COUNT = len(ITEMS)

# 208 items, 68 recipes
assert ITEM_COUNT == 242


def get_item(name):
    for n, item in enumerate(ITEMS):
        if item['name'] == name:
            return n
    return None


RUNES = load_source_file('resources/runes.json')
RUNE_COUNT = len(RUNES)

assert RUNE_COUNT == 6

SHOPS = load_source_file('resources/shops.json')
SHOP_COUNT = len(SHOPS)

assert SHOP_COUNT == 4

NEUTRALS = load_source_file('resources/neutrals.json')
NEUTRAL_COUNT = len(NEUTRALS)

assert NEUTRAL_COUNT == 18

ABILITIES = load_source_file('resources/abilities.json')
ABILITY_COUNT = len(ABILITIES)

assert ABILITY_COUNT == 2031

HEROES = load_source_file('resources/heroes.json')
HERO_COUNT = len(HEROES)

assert HERO_COUNT == 122

ROLES = load_source_file('resources/roles.json')

MAX_ABILITY_COUNT_PER_HEROES = 24


class HeroLookup:
    """Help bring some consistency with ability index.
    Move all the talent up to the end of the ability array.
    This makes the talent consistent with invoker ability array which is the big exception

    Examples
    --------
    >>> h = HERO_LOOKUP.from_id(112)
    >>> for a in h['abilities']:
    ...     print(a)
    winter_wyvern_arctic_burn
    winter_wyvern_splinter_blast
    winter_wyvern_cold_embrace
    generic_hidden
    generic_hidden
    winter_wyvern_winters_curse
    None
    None
    None
    special_bonus_unique_winter_wyvern_5
    special_bonus_attack_damage_50
    special_bonus_hp_275
    special_bonus_night_vision_400
    special_bonus_unique_winter_wyvern_1
    special_bonus_unique_winter_wyvern_7
    special_bonus_unique_winter_wyvern_3
    special_bonus_unique_winter_wyvern_4
    None
    None
    None
    None
    None
    None
    None

    Using the remapped ability index

    >>> h = HERO_LOOKUP.from_id(112)
    >>> for i in h['remap']:
    ...     print(h['abilities'][i])
    winter_wyvern_arctic_burn
    winter_wyvern_splinter_blast
    winter_wyvern_cold_embrace
    generic_hidden
    generic_hidden
    winter_wyvern_winters_curse
    None
    None
    None
    None
    None
    None
    None
    None
    None
    None
    special_bonus_unique_winter_wyvern_5
    special_bonus_attack_damage_50
    special_bonus_hp_275
    special_bonus_night_vision_400
    special_bonus_unique_winter_wyvern_1
    special_bonus_unique_winter_wyvern_7
    special_bonus_unique_winter_wyvern_3
    special_bonus_unique_winter_wyvern_4

    Invoker

    >>> h = HERO_LOOKUP.from_id(74)
    >>> for i in h['remap']:
    ...     print(h['abilities'][i])
    invoker_quas
    invoker_wex
    invoker_exort
    invoker_empty1
    invoker_empty2
    invoker_invoke
    invoker_cold_snap
    invoker_ghost_walk
    invoker_tornado
    invoker_emp
    invoker_alacrity
    invoker_chaos_meteor
    invoker_sun_strike
    invoker_forge_spirit
    invoker_ice_wall
    invoker_deafening_blast
    special_bonus_unique_invoker_10
    special_bonus_unique_invoker_6
    special_bonus_unique_invoker_13
    special_bonus_unique_invoker_9
    special_bonus_unique_invoker_3
    special_bonus_unique_invoker_5
    special_bonus_unique_invoker_2
    special_bonus_unique_invoker_11
    """

    def __init__(self):
        self.ability_count = 0
        self._from_id = dict()
        self._from_name = dict()
        self._ability_remap = dict()

        for offset, hero in enumerate(HEROES):
            self.ability_count = max(self.ability_count, len(hero.get('abilities', [])))
            self._from_id[hero['id']] = hero
            self._from_name[hero['name']] = hero
            hero['offset'] = offset
            hero['remap'] = self._remap_abilities(hero)

    def _remap_abilities(self, hero):
        # `special` count = 960 | 121 * 8 = 968
        # npc_dota_hero_target_dummy is not a real hero
        remapped_talents = []
        remapped_abilities = []

        for i, ability in enumerate(hero.get('abilities', [])):
            if ability and 'special' in ability:
                remapped_talents.append(i)
            else:
                remapped_abilities.append(i)

        abilites = [None] * MAX_ABILITY_COUNT_PER_HEROES

        for i in range(len(remapped_abilities)):
            abilites[i] = remapped_abilities[i]

        # insert talents at the end
        for i in range(len(remapped_talents)):
            abilites[- len(remapped_talents) + i] = remapped_talents[i]

        return abilites

    def from_id(self, id):
        """Get hero info from its id"""
        return self._from_id.get(id)

    def from_name(self, name):
        """Get hero info from its name"""
        return self._from_name.get(name)

    def from_offset(self, offset):
        """Get hero info from its offset"""
        return HEROES[offset]

    @staticmethod
    def remap(hero, aid):
        """Remap hero ability id to game ability id

        Examples
        --------
        >>> from luafun.game.action import AbilitySlot
        >>> am = HERO_LOOKUP.from_id(1)
        >>> HeroLookup.remap(am, AbilitySlot.Q)
        17
        >>> HeroLookup.remap(am, AbilitySlot.Talent42)
        33

        >>> invoker = HERO_LOOKUP.from_id(74)
        >>> HeroLookup.remap(invoker, AbilitySlot.Q)
        17
        >>> HeroLookup.remap(invoker, AbilitySlot.Talent42)
        40
        """
        n = len(ItemSlot)

        if n <= aid < 41:
            return hero['remap'][aid - n] + n

        return aid

    def ability_from_id(self, hid, aid):
        """Get the game ability from hero id and model ability id"""
        return HeroLookup.remap(self._from_id.get(hid), aid)

    def ability_from_name(self, name, aid):
        """Get the game ability from hero name and model ability id"""
        return HeroLookup.remap(self._from_name.get(name), aid)


HERO_LOOKUP = HeroLookup()


class Lanes(IntEnum):
    Roam = 0
    Top = 1
    Mid = 2
    Bot = 3


class RuneSlot(IntEnum):
    PowerUpTop = 0
    PowerUpBottom = 1
    BountyRiverTop = 2
    BountyRadiant = 3
    BountyRiverBottom = 4
    BountyDire = 5


# indices are zero based with 0-5 corresponding to inventory, 6-8 are backpack and 9-15 are stash
class ItemSlot(IntEnum):
    # Inventory
    Item0 = 0
    Item1 = 1
    Item2 = 2
    Item3 = 3
    Item4 = 4
    Item5 = 5
    Bakcpack1 = 6
    Bakcpack2 = 7
    Bakcpack3 = 8
    Stash1 = 9
    Stash2 = 10
    Stash3 = 11
    Stash4 = 12
    Stash5 = 13
    Stash6 = 14
    Item15 = 15  # TP
    Item16 = 16  # Neutral ?


assert len(ItemSlot) == 17, '17 item slots'


# might have to normalize talent so it is easier to learn
class SpellSlot(IntEnum):
    Ablity0 = 0  # Q                 | invoker_quas
    Ablity1 = 1  # W                 | invoker_wex
    Ablity2 = 2  # E                 | invoker_exort
    Ablity3 = 3  # D generic_hidden  | invoker_empty1
    Ablity4 = 4  # F generic_hidden  | invoker_empty2
    Ablity5 = 5  # R                 | invoker_invoke
    Ablity6 = 6  # .                 | invoker_cold_snap
    Ablity7 = 7  # .                 | invoker_ghost_walk
    Ablity8 = 8  # .                 | invoker_tornado
    Ablity9 = 9  # .                 | invoker_emp
    Ablity10 = 10  # .                 | invoker_alacrity
    Ablity11 = 11  # .                 | invoker_chaos_meteor
    Ablity12 = 12  # .                 | invoker_sun_strike
    Ablity13 = 13  # .                 | invoker_forge_spirit
    Ablity14 = 14  # .                 | invoker_ice_wall
    Ablity15 = 15  # .                 | invoker_deafening_blast
    Ablity16 = 16  # Talent 1  (usually but the talent offset can be shifted)
    Ablity17 = 17  # Talent 2  example: rubick, invoker, etc..
    Ablity18 = 18  # Talent 3
    Ablity19 = 19  # Talent 4  98 heroes follow the pattern above
    Ablity20 = 20  # Talent 5
    Ablity21 = 21  # Talent 6
    Ablity22 = 22  # Talent 7
    Ablity23 = 23  # Talent 8


assert len(SpellSlot) == 24, '24 abilities'


# Could bundle the courier action as a hero action
class CourierAction(IntEnum):
    BURST = 0
    # hidden
    # ENEMY_SECRET_SHOP   = 1
    RETURN = 2
    SECRET_SHOP = 3
    TAKE_STASH_ITEMS = 4
    TRANSFER_ITEMS = 5
    # bots will have to do 2 actions for those
    # not a big deal IMO
    # TAKE_AND_TRANSFER_ITEMS
    # COURIER_ACTION_SIDE_SHOP
    # COURIER_ACTION_SIDE_SHOP2


class HeightLevel(IntEnum):
    River = 0
    Low = 1
    High = 2
    Elevated = 3
    Cliffs = 4
    Valley = 5


def rank_to_offset(rank):
    return rank - 10


class Rank(IntEnum):
    # 80 is the rank sent by OpenDota
    # with offset it back by 10 so we get numbers starting from 0
    Immortal  = rank_to_offset(80)
    Divine9   = rank_to_offset(79)
    Divine8   = rank_to_offset(78)
    Divine7   = rank_to_offset(77)
    Divine6   = rank_to_offset(76)
    Divine5   = rank_to_offset(75)
    Divine4   = rank_to_offset(74)
    Divine3   = rank_to_offset(73)
    Divine2   = rank_to_offset(72)
    Divine1   = rank_to_offset(71)
    Divine0   = rank_to_offset(70)
    Ancient9  = rank_to_offset(69)
    Ancient8  = rank_to_offset(68)
    Ancient7  = rank_to_offset(67)
    Ancient6  = rank_to_offset(66)
    Ancient5  = rank_to_offset(65)
    Ancient4  = rank_to_offset(64)
    Ancient3  = rank_to_offset(63)
    Ancient2  = rank_to_offset(62)
    Ancient1  = rank_to_offset(61)
    Ancient0  = rank_to_offset(60)
    Legend9   = rank_to_offset(59)
    Legend8   = rank_to_offset(58)
    Legend7   = rank_to_offset(57)
    Legend6   = rank_to_offset(56)
    Legend5   = rank_to_offset(55)
    Legend4   = rank_to_offset(54)
    Legend3   = rank_to_offset(53)
    Legend2   = rank_to_offset(52)
    Legend1   = rank_to_offset(51)
    Legend0   = rank_to_offset(50)
    Archon9   = rank_to_offset(49)
    Archon8   = rank_to_offset(48)
    Archon7   = rank_to_offset(47)
    Archon6   = rank_to_offset(46)
    Archon5   = rank_to_offset(45)
    Archon4   = rank_to_offset(44)
    Archon3   = rank_to_offset(43)
    Archon2   = rank_to_offset(42)
    Archon1   = rank_to_offset(41)
    Archon0   = rank_to_offset(40)
    Crusader9 = rank_to_offset(39)
    Crusader8 = rank_to_offset(38)
    Crusader7 = rank_to_offset(37)
    Crusader6 = rank_to_offset(36)
    Crusader5 = rank_to_offset(35)
    Crusader4 = rank_to_offset(34)
    Crusader3 = rank_to_offset(33)
    Crusader2 = rank_to_offset(32)
    Crusader1 = rank_to_offset(31)
    Crusader0 = rank_to_offset(30)
    Guardian9 = rank_to_offset(29)
    Guardian8 = rank_to_offset(28)
    Guardian7 = rank_to_offset(27)
    Guardian6 = rank_to_offset(26)
    Guardian5 = rank_to_offset(25)
    Guardian4 = rank_to_offset(24)
    Guardian3 = rank_to_offset(23)
    Guardian2 = rank_to_offset(22)
    Guardian1 = rank_to_offset(21)
    Guardian0 = rank_to_offset(20)
    Herald9   = rank_to_offset(19)
    Herald8   = rank_to_offset(18)
    Herald7   = rank_to_offset(17)
    Herald6   = rank_to_offset(16)
    Herald5   = rank_to_offset(15)
    Herald4   = rank_to_offset(14)
    Herald3   = rank_to_offset(13)
    Herald2   = rank_to_offset(12)
    Herald1   = rank_to_offset(11)
    Herald0   = rank_to_offset(10)
    Size = 71
