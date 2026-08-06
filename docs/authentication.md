# Authentication

JWT (HS256), two independent token types sharing one verify path:
- User tokens (`sub` = user id) — register/login.
- Session tokens (`sub` = session id) — minted per chat session.

See `app/utils/auth.py` and the two dependencies in `app/api/v1/auth.py`
(`get_current_user`, `get_current_session`).
