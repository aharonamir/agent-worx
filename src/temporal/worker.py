from __future__ import annotations

import asyncio

from temporalio.client import Client

from src.temporal.config import get_temporal_config


async def connect_client() -> Client:
    config = get_temporal_config()
    return await Client.connect(config.host, namespace=config.namespace)


def main() -> None:
    asyncio.run(connect_client())


if __name__ == "__main__":
    main()
