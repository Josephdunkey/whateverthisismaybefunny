import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8888/v1/default/banks/bookcompiler/documents/7b28722a-ce9d-4b07-82e8-e20623fa53c6", timeout=20) as r:
    data = json.loads(r.read().decode("utf-8"))
print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])