import asyncio
import logging
from logging.handlers import RotatingFileHandler
from . import config, llm
from .roles import ALL_AGENTS


def setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(); sh.setFormatter(fmt); root.addHandler(sh)
    fh = RotatingFileHandler(config.LOG_PATH, maxBytes=20_000_000, backupCount=5)
    fh.setFormatter(fmt); root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def wait_for_model():
    log = logging.getLogger("runner")
    while not await llm.healthy():
        log.warning("modelo no disponible en %s; esperando…", config.LLM_BASE_URL)
        await asyncio.sleep(10)
    log.info("modelo disponible: %s", config.LLM_MODEL)


async def main():
    setup_logging()
    await wait_for_model()
    agents = [cls() for cls in ALL_AGENTS]
    logging.getLogger("runner").info("lanzando %d agentes 24/7", len(agents))
    await asyncio.gather(*(a.run_forever() for a in agents))


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
