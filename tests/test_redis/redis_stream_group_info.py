import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

for g in r.xinfo_groups("stream:file_path"):
    print(
        g["name"],
        "last-delivered-id =",
        g["last-delivered-id"],
        "pending =",
        g["pending"],
        "entries-read =",
        g.get("entries-read"),
        "lag =",
        g.get("lag"),
    )
