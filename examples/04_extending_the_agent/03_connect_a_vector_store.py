import asyncio
import os

from narada import Agent, AgentKind, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()

    try:
        vector_stores = await env.vector_stores.list()

        print("Available managed vector stores:")
        if not vector_stores:
            print("- None found")
            return

        for vector_store in vector_stores:
            print(
                f"- id={vector_store.id!r}, "
                f"name={vector_store.name!r}, "
                f"path={vector_store.path!r}, "
                f"files={vector_store.fileCount}"
            )

        vector_store_id = os.getenv("NARADA_VECTOR_STORE_ID")
        vector_store_path = os.getenv("NARADA_VECTOR_STORE_PATH")

        if vector_store_id and vector_store_path:
            raise ValueError(
                "Set only one of NARADA_VECTOR_STORE_ID or NARADA_VECTOR_STORE_PATH"
            )

        if vector_store_id:
            vector_store = await env.vector_stores.get(id=vector_store_id)
        elif vector_store_path:
            vector_store = await env.vector_stores.get(path=vector_store_path)
        else:
            vector_store = vector_stores[0]
            print("\nNo vector store selector was provided; using the first result.")

        print(
            "\nUsing vector store: "
            f"id={vector_store.id!r}, name={vector_store.name!r}, path={vector_store.path!r}"
        )

        prompt = os.getenv(
            "NARADA_VECTOR_STORE_PROMPT",
            (
                "Use the attached vector store to answer this request. "
                "Summarize its main subject and cite the source filename for each "
                "important claim. If the vector store does not contain enough "
                "information, say so explicitly."
            ),
        )
        response = await Agent(
            environment=env,
            kind=AgentKind.PRODUCTIVITY,
        ).run(
            prompt=prompt,
            vector_stores=[vector_store],
        )

        print("Response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())
