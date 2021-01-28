import logging
import json
import multiprocessing as mp

from luafun.game.inspect.base import BasePage
from luafun.game.action import IPCMessageBuilder

import rpcjs.elements as html

log = logging.getLogger(__name__)


class Config:
    def __init__(self, app):
        # this is supposed to be inverted, not a bug
        self.rpc_recv = app.rpc_send
        self.rpc_send = app.rpc_recv
        self.state = app.state


class Actions(BasePage):
    def routes(self):
        return [
            '/action/<string:action>',
            '/action/<string:action>/<int:player>',
            '/action/<string:action>/<int:player>/<float:x>x<float:y>',
        ]

    def __init__(self, app):
        super(Actions, self).__init__(app)
        self.title = 'Action'
        self.process = None

    def main(self, action, player=0, x=0, y=0):
        if action == 'stop':
            self.state['running'] = False

        if action == 'info':
            return self.send_get_info()

        if action == 'move':
            return self.send_move_action(player, x, y)

        if action == 'play':
            return self.start()

        page = self.env.get_template('state.html')
        return page.render(code='Stopped', state=self.state)

    def start(self):
        """Start a new environment running"""
        from luafun.dotaenv import main

        config = Config(self.app)
        self.state['running'] = True
        self.process = mp.Process(
            target=main,
            args=(config,)
        )
        self.process.start()
        page = self.env.get_template('state.html')
        return page.render(code='Starting', state=self.state)

    def send_action(self, action):
        self.rpc_send.put(dict(attr='send_message', args=[action]))
        _ = self.fetch()

        page = self.env.get_template('base.html')
        return page.render(body=f'<pre>{json.dumps(action, indent=2)}</pre>', state=self.state)

    def send_get_info(self):
        b = IPCMessageBuilder()
        p = b.player(0)
        p.MoveToLocation([0, 0])
        p.act[0] = 31
        m = b.build()
        return self.send_action(m)

    def send_move_action(self, player, x, y):
        b = IPCMessageBuilder()
        p = b.player(player)
        p.MoveToLocation([x, y])
        m = b.build()
        return self.send_action(m)

