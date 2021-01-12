import json
import os

TEAM_RADIANT = 2
TEAM_DIRE = 3


def new_ipc_message():
    """Basic ipc message we can send to the bots"""
    return {
        'uid': 0,
        TEAM_RADIANT: {
            0: dict(),
            1: dict(),
            2: dict(),
            3: dict(),
            4: dict(),
        },
        TEAM_DIRE: {
            5: dict(),
            6: dict(),
            7: dict(),
            8: dict(),
            9: dict(),
        }
    }


uid = 0

def ipc_send(f2, data):
    """Write a lua file with the data we want bots to receive"""
    global uid

    f1 = f2 + '_tmp'

    if os.path.exists(f2):
        os.remove(f2)

    # Keep track of the message id we are sending
    uid += 1
    data['uid'] = uid
    json_string = json.dumps(data, separators=(',', ':'))

    with open(f1, 'w') as file:
        file.write(f'return \'{json_string}\'')

    # Renaming is almost always atomic
    os.rename(f1, f2)
