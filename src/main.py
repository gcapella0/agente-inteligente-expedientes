from src.agents.watcher_agent import WatcherAgent
from src.core.logger import logger


def main() -> None:
    """
    Punto de entrada del servicio de Watcher.

    Ejecuta el WatcherAgent en modo continuo.
    """

    logger.info(" Iniciando servicio Watcher Agent desde main.py")
    watcher = WatcherAgent()
    watcher.run()


if __name__ == "__main__":
    main()

