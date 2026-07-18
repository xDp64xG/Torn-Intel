from cli.parser import build_parser
from cli.commands import CLI
from core.engine import TornIntel


def main():

    parser = build_parser()

    args = parser.parse_args()

    app = TornIntel()

    cli = CLI(app)

    cli.execute(args)


if __name__ == "__main__":
    main()