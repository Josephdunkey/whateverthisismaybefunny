import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8888/v1/default/banks/bookcompiler/documents?limit=10", timeout=20) as r:
    print(r.read().decode("utf-8"))