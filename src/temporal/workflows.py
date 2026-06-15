from __future__ import annotations

from datetime import timedelta

from temporalio import activity, workflow


@activity.defn
async def hello_activity(name: str) -> str:
    return f"Hello, {name}!"


@workflow.defn
class HelloWorkflow:
    @workflow.run
    async def run(self, name: str) -> str:
        return await workflow.execute_activity(
            hello_activity,
            name,
            start_to_close_timeout=timedelta(seconds=10),
        )
