import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8888/v1/default/banks/hermes/documents?limit=5", timeout=20) as r:
    print(r.read().decode("utf-8"))