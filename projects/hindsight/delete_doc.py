import json, urllib.request
req = urllib.request.Request("http://127.0.0.1:8888/v1/default/banks/bookcompiler/documents/setup-verification-001", method="DELETE")
with urllib.request.urlopen(req, timeout=30) as r:
    print(r.status, r.read().decode("utf-8"))