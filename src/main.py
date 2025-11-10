"""Punto de entrada principal para el Watcher Agent."""
from src.agents.watcher_agent import WatcherAgent
from src.core.logger import logger


def main() -> None:
    """Función principal que inicia el Watcher Agent."""
    logger.info("Watcher started...")
    watcher = WatcherAgent()
    watcher.run()


if __name__ == "__main__":
    main()

