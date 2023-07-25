import aioredis

redis = aioredis.from_url(
    "redis://localhost:6379",
    encoding="utf-8",
    decode_responses=True,
)
