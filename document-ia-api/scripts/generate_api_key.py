import asyncio

from document_ia_api.application.services.api_key.api_key_helper import ApiKeyHelper


async def main() -> None:
    helper = ApiKeyHelper()
    presented, prefix, chk, key_hash = helper.generate_new_api_key()

    print("Generated API key for Document IA:\n")
    print(f"  API key (presented): {presented}")
    print(f"  Prefix:             {prefix}")
    print(f"  Checksum:           {chk}")
    print(f"  Argon2 hash:        {key_hash}\n")
    print("Store the prefix and hash in the database; never log or expose the hash publicly.")


if __name__ == "__main__":
    asyncio.run(main())
