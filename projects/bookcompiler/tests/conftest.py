import os
os.environ.setdefault("BOOKCOMPILER_EMBED_BACKEND", "local")
os.environ.setdefault("BOOKCOMPILER_RERANK", "0")
os.environ.pop("BOOKCOMPILER_EMBED_BASE_URL", None)

os.environ["HINDSIGHT_ENABLED"] = "0"
os.environ["HINDSIGHT_BASE_URL"] = ""
