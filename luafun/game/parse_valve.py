from collections import defaultdict


class StartObject:
    def __repr__(self):
        return 'StartObj'


class EndObject:
    def __repr__(self):
        return 'EndObj'


class EndLine:
    def __repr__(self):
        return 'EndLine'


class NewValue:
    def __init__(self, s):
        self.value = s

    def __repr__(self):
        return self.value


class Lexer:
    def __init__(self, filename):
        with open(filename, "r") as f:
            self.content = f.read()

        self.pos = 0
        self.buffer = ''
        self.parsing_string = False
        self.parsing_comment = False
        self.previous = None

    def __iter__(self):
        return self

    def process_character(self, c):
        if self.parsing_string:
            if c == '"':
                self.parsing_string = False
                value = self.buffer
                self.buffer = ''
                return NewValue(value)
            else:
                self.buffer += c

        if self.previous == '/' and c == '/':
            self.parsing_comment = True

        if self.parsing_comment:
            if c == '\n':
                self.parsing_comment = False
            return None

        if c in (' ', '\t'):
            return None

        if c == '{':
            return StartObject()

        if c == '}':
            return EndObject()

        if c == '\n':
            return EndLine()

        if c == '"':
            self.parsing_string = True

        if c == '/':
            self.previous = '/'

    def __next__(self):
        tok = None

        while tok is None and self.pos < len(self.content):
            tok = self.process_character(self.content[self.pos])
            self.pos += 1

        if tok is None and self.pos == len(self.content):
            raise StopIteration

        return tok


constants = dict(
    # "ability_type"
    DOTA_ABILITY_TYPE_BASIC = 0,
    DOTA_ABILITY_TYPE_ULTIMATE = 1,
    DOTA_ABILITY_TYPE_ATTRIBUTES = 2,
    # "ability_behavior"
    DOTA_ABILITY_BEHAVIOR_HIDDEN=1,
    DOTA_ABILITY_BEHAVIOR_PASSIVE = 2,
    DOTA_ABILITY_BEHAVIOR_NO_TARGET = 4,
    DOTA_ABILITY_BEHAVIOR_UNIT_TARGET = 8,
    DOTA_ABILITY_BEHAVIOR_POINT = 16,
    DOTA_ABILITY_BEHAVIOR_AOE = 32,
    DOTA_ABILITY_BEHAVIOR_NOT_LEARNABLE = 64,
    DOTA_ABILITY_BEHAVIOR_CHANNELLED = 128,
    DOTA_ABILITY_BEHAVIOR_ITEM = 256,
    DOTA_ABILITY_BEHAVIOR_TOGGLE = 512,
    # "ability_unit_target_type":
    DOTA_UNIT_TARGET_NONE = 0,
    DOTA_UNIT_TARGET_FRIENDLY_HERO = 5,
    DOTA_UNIT_TARGET_FRIENDLY_BASIC = 9,
    DOTA_UNIT_TARGET_FRIENDLY = 13,
    DOTA_UNIT_TARGET_ENEMY_HERO = 6,
    DOTA_UNIT_TARGET_ENEMY_BASIC = 10,
    DOTA_UNIT_TARGET_ENEMY = 14,
    DOTA_UNIT_TARGET_ALL = 15,
)


class Parser:
    def __init__(self, filename):
        self.lexer = Lexer(filename)
        self.root = dict()
        self.objects = [self.root]
        self.current_key = None
        self.current_value = None
        self.replace_enums = True
        names = [
            'AbilityUnitDamageType',
            'SpellImmunityType',
            'AbilityBehavior',
            'HasScepterUpgrade',
            'AbilityCastPoint',
            'AbilityCooldown',
            'AbilityManaCost',
            'AbilityCastRange',
            'SpellDispellableType',
            'AbilityUnitDamageType',
            'AbilityDuration',
            'AbilityChannelTime',
            'AbilityUnitTargetFlags',
            'AbilityCastAnimation',
            'AbilityType',
            'AbilityUnitTargetTeam',
            'AbilityUnitTargetType',
            'AbilityDamage',
            'HasShardUpgrade'
        ]
        self.ability_spec = defaultdict(int)
        for n in names:
            self.ability_spec[n] = 0

    def parse(self):
        for tok in self.lexer:
            if isinstance(tok, StartObject):
                self.on_start_obj()

            if isinstance(tok, EndObject):
                self.on_end_obj()

            if isinstance(tok, NewValue):
                self.on_value(tok.value)

            if isinstance(tok, EndLine):
                self.on_end_line()

        return self.root

    def on_start_obj(self):
        assert self.current_key is not None, "Object need a Name"
        obj = dict()
        self.objects[-1][self.current_key] = obj
        self.objects.append(obj)
        self.current_key = None

    @staticmethod
    def trypopitem(d, default):
        try:
            return d.popitem()
        except KeyError:
            return default

    def on_end_obj(self):
        obj = self.objects.pop()
        specials = obj.get('AbilitySpecial', dict())
        new_spec = dict()

        # Object post processing to make it more workable
        for k, v in specials.items():
            if not isinstance(v, dict):
                print(k, v, obj)
                continue

            var_type = v.pop('var_type')
            name, values = Parser.trypopitem(v, [None, ''])
            if name:
                new_spec[name] = values.split(' ')

                if 'special' not in name and 'seasonal' not in name:
                    self.ability_spec[name] += 1

        # for k, _ in obj.items():
        #     if 'special' not in k and 'seasonal' not in k:
        #         self.ability_spec[k] += 1

        if new_spec:
            obj['AbilitySpecial'] = new_spec

    def on_value(self, value):
        if self.current_key is None:
            self.current_key = value
        else:
            self.current_value = value

            if self.replace_enums:
                for k, v in constants.items():
                    if k in self.current_value:
                        self.current_value = self.current_value.replace(k, str(v))

    def on_end_line(self):
        if self.current_value is not None:
            self.objects[-1][self.current_key] = self.current_value
            self.current_key = None
            self.current_value = None


if __name__ == '__main__':
    p = Parser('C:/Users/Newton/work/luafun/resources/npc_abilities.txt')
    p.parse()

    import json

    print(json.dumps(p.root['DOTAAbilities']['antimage_mana_break'], indent=2))
    print(p.ability_spec)
    print(len(p.ability_spec))

    reused_comp = 0
    for k, c in p.ability_spec.items():
        if c > 1:
            print(k, c)
            reused_comp += 1

    print(reused_comp)
    print(len(p.ability_spec))
    print(len(p.root['DOTAAbilities']))