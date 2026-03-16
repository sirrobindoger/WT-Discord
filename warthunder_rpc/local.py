import logging

from .runtime import RuntimeOptions, WarThunderRPCApp


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = WarThunderRPCApp(
        RuntimeOptions(
            mode="local",
            prompt_for_username=True,
            logger=logging.getLogger("warthunder_rpc.local"),
        )
    )
    app.run_forever()


if __name__ == "__main__":
    main()
