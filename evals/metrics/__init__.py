"""Loads every metric prompt in prompts/ as an evaluatable metric."""

import os

metrics = []
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

for file in os.listdir(PROMPTS_DIR):
    if file.endswith(".md"):
        with open(os.path.join(PROMPTS_DIR, file), "r") as f:
            metrics.append({"name": file.replace(".md", ""), "prompt": f.read()})
