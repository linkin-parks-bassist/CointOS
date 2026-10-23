"""Keep fatal Python failures out of the service's mechanical restart loop."""
import traceback


def run(start):
    try:
        return start()
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)


def main():
    def start():
        from cointos.daemon import main as daemon
        daemon()
    run(start)


if __name__ == "__main__":
    main()
