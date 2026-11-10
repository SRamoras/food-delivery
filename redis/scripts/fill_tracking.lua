-- Creates the tracking hash only if it is still missing, with its TTL in the same step.
-- A status change can land while the API is reading PostgreSQL on a cache miss; without
-- this check the older status read from PG would overwrite the newer one.
-- KEYS[1]: fd:order:{id}:track. ARGV[1]: TTL in seconds. ARGV[2..]: field, value, ...
if redis.call('EXISTS', KEYS[1]) == 1 then
  return 0
end
redis.call('HSET', KEYS[1], unpack(ARGV, 2))
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
