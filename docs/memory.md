# Memory

Long-term memory is self-hosted via mem0 + pgvector
(`app/services/memory.py`), cached through `app/core/cache.py`. Anonymous
sessions (no `user_id`) skip long-term memory entirely.
