from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from src.temporal.config import get_temporal_config
from src.temporal.workflows import HelloWorkflow, hello_activity


async def connect_client() -> Client:
    config = get_temporal_config()
    return await Client.connect(config.host, namespace=config.namespace)


async def run_worker() -> None:
    config = get_temporal_config()
    client = await Client.connect(config.host, namespace=config.namespace)
    worker = Worker(
        client,
        task_queue="agent-platform-tasks",
        workflows=[HelloWorkflow],
        activities=[hello_activity],
    )
    print(f"Worker started. Connected to {config.host}, namespace={config.namespace}")
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
