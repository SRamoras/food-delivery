"""Redis client and the Lua scripts used by the app."""

import redis
from redis.commands.core import Script

from app.config import ROOT_DIR, settings

# decode_responses=True: values come back as str instead of bytes.
# The client holds a thread-safe connection pool: create it once and share it.
client: redis.Redis = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
)

SCRIPTS_DIR = ROOT_DIR / "redis" / "scripts"


def load_script(name: str) -> Script:
    """Register redis/scripts/<name>.lua once, at import time.

    register_script only computes the SHA1 locally. Each call runs EVALSHA, and if
    Redis does not know the script yet (e.g. after a restart) redis-py sends it with
    EVAL automatically. The whole script runs atomically: no other command runs
    between its steps.
    """
    return client.register_script((SCRIPTS_DIR / f"{name}.lua").read_text())


# Scripts are registered here as they are written.
courier_position = load_script("courier_position")
