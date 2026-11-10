-- Stores a courier's position and refreshes their online key, atomically (F7).
-- KEYS[1] fd:couriers:geo            KEYS[2] fd:courier:{id}:online
-- ARGV[1] lng  ARGV[2] lat  ARGV[3] courier id (geo member)  ARGV[4] online TTL (s)
-- ARGV[5] "1" = only if already online (POST /position), "0" = go online (POST /online)
-- Returns 1 if stored, 0 if the courier was offline and ARGV[5] is "1".
--
-- One script, so Redis runs the check, GEOADD and SET with nothing in between: a
-- courier can never be on the map without an online key, and an /offline that
-- arrives at the same time runs entirely before or entirely after this.
if ARGV[5] == '1' and redis.call('EXISTS', KEYS[2]) == 0 then
    return 0
end
redis.call('GEOADD', KEYS[1], ARGV[1], ARGV[2], ARGV[3])
-- TTL in the same command as the write: no positions for 30 s = offline.
redis.call('SET', KEYS[2], '1', 'EX', ARGV[4])
return 1
