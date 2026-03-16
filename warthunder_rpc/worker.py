import logging

from .runtime import RuntimeOptions, WarThunderRPCApp


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = WarThunderRPCApp(
        RuntimeOptions(
            mode="worker",
            prompt_for_username=False,
            logger=logging.getLogger("warthunder_rpc.worker"),
        )
    )
    app.run_forever()


if __name__ == "__main__":
    main()
