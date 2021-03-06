from argparse import ArgumentParser
import logging

from luafun.dotaenv import dota2_environment
from luafun.utils.options import option
from luafun.model.inference import InferenceEngine
from luafun.model.training import TrainEngine


def main(config=None):
    """This simply runs the environment until the game finishes, default to RandomActor (actions are random)
    It means bots will not do anything game winning, if drafting is enabled nothing will be drafted
    """

    parser = ArgumentParser()
    parser.add_argument('--draft', action='store_true', default=False,
                        help='Enable bot drafting')

    parser.add_argument('--mode', type=str, default='allpick_nobans',
                        help='Game mode')

    parser.add_argument('--path', type=str, default=option('dota.path', None),
                        help='Custom Dota2 game location')

    parser.add_argument('--render', action='store_true', default=False,
                        help='Render the game on screen')

    parser.add_argument('--speed', type=float, default=4,
                        help='Speed multiplier')

    parser.add_argument('--interactive', action='store_true', default=False,
                        help='Make a human create the lobby')

    # --model socket://192.163.0.102:8080
    parser.add_argument('--model', type=str, default='random',
                        help='Model name factory, defaults to a random action sampler')

    # --trainer socket://192.163.0.103:8081
    parser.add_argument('--trainer', type=str, default='random',
                        help='')

    args = parser.parse_args()
    game = dota2_environment(args.mode, args.path, config=config)

    if game is None:
        return

    # logging.basicConfig(level=logging.INFO)
    logging.basicConfig(level=logging.DEBUG)

    game.options.dedicated = not args.render
    game.options.interactive = args.interactive
    game.options.host_timescale = args.speed
    game.options.draft = int(args.draft)

    obs_size = game.observation_space
    train = TrainEngine(args.trainer, args.model, (obs_size, 10, 16))
    model = InferenceEngine(args.model, train)

    with game:
        # Initialize Drafter & Encoders
        if game.options.draft:
            model.init_draft()
        # ---

        state, reward, done, info = game.initial()

        # Draft here if enabled
        while game.running:

            if game.options.draft:
                pass

            break

        game.wait_end_draft()
        model.close_draft()
        model.init_play(game)

        uid = game.options.game_id

        # Play the game
        while game.running:
            # start issuing orders here
            action, logprob, filter = model.action(uid, state)

            # select an action to perform
            state, reward, done, info = game.step(action)

            # push the new observation
            train.push(uid, state, reward, done, info, action, logprob, filter)

            if train.ready():
                train.train()

            if state is None:
                break

            if game.cnt > 0 and game.cnt % 100 == 0:
                print(f'Step time {game.avg / game.cnt:.4f} Reward {reward[0]}')

        print('Game Finished')

    print('Done')


if __name__ == '__main__':
    main()
