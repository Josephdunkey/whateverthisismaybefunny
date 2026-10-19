import json, urllib.request
payload = {"items":[{"content":"用户偏好：回答问题时先给结论，再给证据；不确定时明确说“不确定”，不要编造。","context":"Hermes setup verification","tags":["preference","style"],"metadata":{"source":"hermes","kind":"preference"}}],"async":True}
req = urllib.request.Request("http://127.0.0.1:8888/v1/default/banks/hermes/memories", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST", headers={"Content-Type":"application/json; charset=utf-8"})
with urllib.request.urlopen(req, timeout=30) as r:
    print(r.read().decode("utf-8"))