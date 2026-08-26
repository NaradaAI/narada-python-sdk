import asyncio
import os

from narada import (
    Agent,
    AgentKind,
    BedrockConnectionConfig,
    BedrockCredentials,
    BrowserEnvironment,
    ExternalVectorStore,
)


async def main() -> None:
    required_environment_variables = (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "NARADA_BEDROCK_KNOWLEDGE_BASE_ID",
    )
    missing_environment_variables = [
        name for name in required_environment_variables if not os.getenv(name)
    ]
    if missing_environment_variables:
        raise RuntimeError(
            "Set the required environment variables: "
            + ", ".join(missing_environment_variables)
        )

    knowledge_base_id = os.environ["NARADA_BEDROCK_KNOWLEDGE_BASE_ID"]
    vector_store = ExternalVectorStore(
        id=os.getenv("NARADA_EXTERNAL_VECTOR_STORE_ID", f"bedrock-{knowledge_base_id}"),
        name=os.getenv("NARADA_EXTERNAL_VECTOR_STORE_NAME", "bedrock-knowledge-base"),
        description=os.getenv(
            "NARADA_EXTERNAL_VECTOR_STORE_DESCRIPTION",
            "An AWS Bedrock Knowledge Base attached to this request.",
        ),
        connection=BedrockConnectionConfig(
            credentials=BedrockCredentials(
                accessKeyId=os.environ["AWS_ACCESS_KEY_ID"],
                secretAccessKey=os.environ["AWS_SECRET_ACCESS_KEY"],
                region=os.environ["AWS_REGION"],
            ),
            knowledgeBaseId=knowledge_base_id,
        ),
    )

    env = BrowserEnvironment()

    try:
        print(
            "Using external vector store: "
            f"name={vector_store.name!r}, "
            f"knowledge_base_id={knowledge_base_id!r}, "
            f"region={vector_store.connection.credentials.region!r}"
        )

        prompt = os.getenv(
            "NARADA_VECTOR_STORE_PROMPT",
            (
                "Use the attached external knowledge base to answer this request. "
                "Summarize its main subject and cite the source URI for each "
                "important claim. If the knowledge base does not contain enough "
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
