import json, time, urllib.request, urllib.error
BASE = "http://127.0.0.1:8888"

def call(method, path, payload=None, timeout=300):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")

print("=== list documents ===")
print(call("GET", "/v1/default/banks/bookcompiler/documents?limit=10"))
print("=== recall ===")
t0 = time.time()
print(call("POST", "/v1/default/banks/bookcompiler/memories/recall",
           {"query": "回答宏观金融问题时应遵守什么引用和表述规则？", "budget": "low", "max_tokens": 1200}, timeout=120))
print("recall seconds %.1f" % (time.time() - t0))
print("=== reflect ===")
t0 = time.time()
print(call("POST", "/v1/default/banks/bookcompiler/reflect",
           {"query": "根据记忆，回答宏观金融问题时应遵守哪些规则？", "budget": "low", "max_tokens": 600}, timeout=300))
print("reflect seconds %.1f" % (time.time() - t0))