# Data Flow — function-by-function trace

This document traces **every request type end-to-end**, naming every function involved and every branch it can take. It complements [`README.md`](README.md) (what the system is) and [`docs/architecture.md`](docs/architecture.md) (narrative overview) with the literal call chain: what calls what, in what order, and under which condition.

Notation: `file.py:function` is the exact symbol; `─▶` is a direct call; branch diamonds in the diagrams are real `if`/`try` branches in the code (referenced by file:line).

## Contents

1. [App startup](#1-app-startup)
2. [Request entry — middleware chain (every request)](#2-request-entry--middleware-chain-every-request)
3. [Authentication & token lifecycle](#3-authentication--token-lifecycle)
   - [3.1 Register](#31-register)
   - [3.2 Login](#32-login)
   - [3.3 Create / list / rename / delete session](#33-create--list--rename--delete-session)
   - [3.4 Token verification (every authenticated request)](#34-token-verification-every-authenticated-request)
   - [3.5 JWT internals — exactly how a token is created and checked](#35-jwt-internals--exactly-how-a-token-is-created-and-checked)
4. [Chat turn — `POST /chatbot/chat`](#4-chat-turn--post-chatbotchat)
5. [Streaming chat turn — `POST /chatbot/chat/stream`](#5-streaming-chat-turn--post-chatbotchatstream)
6. [The chat ⇄ tool_call graph loop, in detail](#6-the-chat--tool_call-graph-loop-in-detail)
7. [LLM call: retry + circular fallback](#7-llm-call-retry--circular-fallback)
8. [Tool execution branches](#8-tool-execution-branches)
9. [Acumatica session-cookie lifecycle](#9-acumatica-session-cookie-lifecycle)
10. [Long-term memory read/write](#10-long-term-memory-readwrite)
11. [Fetch / clear history](#11-fetch--clear-history)
12. [Function index (file:line)](#12-function-index-fileline)

---

## 1. App startup

`app/main.py` runs at import time, then `lifespan()` runs once when Uvicorn boots the app.

```mermaid
flowchart TD
    A["import app.main"] --> B["load_dotenv()"]
    B --> C["observability.py: langfuse_init()"]
    C --> D{"LANGFUSE_TRACING_ENABLED?"}
    D -- "no" --> E["skip — log langfuse_tracing_disabled"]
    D -- "yes" --> F["Langfuse(...) + auth_check()"]
    F --> G["FastAPI(..., lifespan=lifespan)"]
    E --> G
    G --> H["setup_metrics(app)  — registers /metrics"]
    H --> I["add_middleware: LoggingContext → Metrics → (DEBUG: Profiling) → CorrelationId"]
    I --> J["app.state.limiter = limiter (slowapi)"]
    J --> K["add CORS middleware"]
    K --> L["include_router(api_router, prefix=API_V1_STR)"]
    L --> M["ASGI server starts → lifespan() context enters"]
    M --> N["cache_service.initialize()"]
    N --> O["agent.create_graph()  — compiles StateGraph, opens Postgres pool, checkpointer.setup()"]
    O --> P["memory_service.initialize()  — mem0 AsyncMemory.from_config(pgvector)"]
    P --> Q["yield — app now serving requests"]
    Q -.->|"on shutdown"| R["cache_service.close()"]
    R --> S["agent._connection_pool.close()"]
```

Each of `cache_service.initialize`, `agent.create_graph`, `memory_service.initialize` is wrapped in its own `try/except` in `main.py:lifespan` (`app/main.py:37-51`) — a failure in one does **not** block the others from attempting to start.

---

## 2. Request entry — middleware chain (every request)

Every HTTP request, regardless of route, passes through this fixed chain before reaching a route handler (order = order of `app.add_middleware` calls in `app/main.py:69-96`; Starlette runs them outermost-last-added, so the effective order below is outer→inner):

```mermaid
flowchart TD
    A["Incoming HTTP request"] --> B["CORSMiddleware"]
    B --> C["CorrelationIdMiddleware — generates/propagates X-Request-ID"]
    C --> D{"DEBUG mode?"}
    D -- yes --> E["ProfilingMiddleware.dispatch() — tracemalloc.start(), Profiler()"]
    D -- no --> F["MetricsMiddleware.dispatch()"]
    E --> F
    F --> G["LoggingContextMiddleware.dispatch()"]
    G --> H["clear_context()"]
    H --> I{"Authorization: Bearer <token> header present?"}
    I -- no --> K["route handler"]
    I -- yes --> J["jwt.decode(token, JWT_SECRET_KEY, [JWT_ALGORITHM])"]
    J --> J2{"decode succeeds and has 'sub'?"}
    J2 -- yes --> J3["bind_context(session_id=sub)"]
    J2 -- no (JWTError) --> J4["swallow silently, continue unauthenticated"]
    J3 --> K
    J4 --> K
    K --> L{"slowapi rate limit for this route exceeded?"}
    L -- yes --> M["_rate_limit_exceeded_handler → 429"]
    L -- no --> N["FastAPI dependency resolution (get_current_user / get_current_session, if declared)"]
    N --> O["route function body runs"]
    O --> P["response returned"]
    P --> Q["MetricsMiddleware: http_requests_total / http_request_duration_seconds .observe()"]
    Q --> R["LoggingContextMiddleware finally: clear_context()"]
    R --> S{"ProfilingMiddleware active and wall_ms ≥ PROFILING_THRESHOLD_SECONDS?"}
    S -- yes --> T["write JSON flamegraph+memory report to PROFILING_DIR"]
    S -- no --> U["discard profiling data"]
    T --> V["response sent to client"]
    U --> V
```

Note the important subtlety at step J/J2: `LoggingContextMiddleware` (`app/core/middleware.py:54-74`) decodes the JWT **only to bind `session_id` into log context** — it does not reject requests with bad/missing tokens. Actual authorization/rejection happens later, inside the `get_current_user`/`get_current_session` FastAPI dependencies (step N), which is where a 401/404/422 would actually be raised.

---

## 3. Authentication & token lifecycle

### 3.1 Register

`POST /api/v1/auth/register` → `app/api/v1/auth.py:register_user`

```mermaid
flowchart TD
    A["register_user(request, user_data: UserCreate)"] --> B["sanitize_email(user_data.email)"]
    B --> C{"valid format?"}
    C -- no --> C1["raise ValueError → 422"]
    C -- yes --> D["password = user_data.password.get_secret_value()"]
    D --> E["validate_password_strength(password)"]
    E --> F{"≥8 chars, upper, lower, digit, special char?"}
    F -- no --> F1["raise ValueError → 422"]
    F -- yes --> G["db_service.get_user_by_email(sanitized_email)"]
    G --> H{"already registered?"}
    H -- yes --> H1["raise HTTPException(400)"]
    H -- no --> I["sanitize_string(username) if present"]
    I --> J["User.hash_password(password)  — bcrypt.hashpw + gensalt()"]
    J --> K["db_service.create_user(email, hashed, username)"]
    K --> L["INSERT INTO user ... ; commit; refresh"]
    L --> M["create_access_token(str(user.id))"]
    M --> N["UserResponse(id, email, username, token)"]
    N --> O["200 response: {id, email, username, token: {access_token, token_type, expires_at}}"]
```

### 3.2 Login

`POST /api/v1/auth/login` (form-encoded) → `app/api/v1/auth.py:login`

```mermaid
flowchart TD
    A["login(email, password, grant_type=Form)"] --> B["sanitize_string(email), sanitize_string(password)"]
    B --> C{"grant_type == 'password'?"}
    C -- no --> C1["raise HTTPException(400) — unsupported grant type"]
    C -- yes --> D["db_service.get_user_by_email(email)"]
    D --> E{"user exists?"}
    E -- no --> F1["raise HTTPException(401)"]
    E -- yes --> F["user.verify_password(password)  — bcrypt.checkpw"]
    F --> G{"match?"}
    G -- no --> F1
    G -- yes --> H["create_access_token(str(user.id))"]
    H --> I["TokenResponse(access_token, token_type='bearer', expires_at)"]
```

### 3.3 Create / list / rename / delete session

All four require a resolved `User` or `Session` from the dependencies in §3.4.

```mermaid
flowchart TD
    subgraph create["POST /auth/session  (needs get_current_user)"]
        A1["create_session(user)"] --> A2["session_id = str(uuid.uuid4())"]
        A2 --> A3["db_service.create_session(session_id, user.id, username=user.username)"]
        A3 --> A4["create_access_token(session_id)  — sub = session_id"]
        A4 --> A5["SessionResponse(session_id, name, token)"]
    end
    subgraph list["GET /auth/sessions  (needs get_current_user)"]
        B1["get_user_sessions(user)"] --> B2["db_service.get_user_sessions(user.id)"]
        B2 --> B3["for each session: create_access_token(session.id) — re-minted, not stored"]
    end
    subgraph rename["PATCH /auth/session/{id}/name  (needs get_current_session)"]
        C1["update_session_name(session_id, name, current_session)"] --> C2{"session_id == current_session.id?"}
        C2 -- no --> C3["403 Cannot modify other sessions"]
        C2 -- yes --> C4["db_service.update_session_name(...)"]
        C4 --> C5["create_access_token(session_id)  — new token returned"]
    end
    subgraph del["DELETE /auth/session/{id}  (needs get_current_session)"]
        D1["delete_session(session_id, current_session)"] --> D2{"session_id == current_session.id?"}
        D2 -- no --> D3["403 Cannot delete other sessions"]
        D2 -- yes --> D4["db_service.delete_session(sanitized_session_id)"]
    end
```

Every session token is **re-minted on demand** (list/rename both call `create_access_token` again) rather than being persisted anywhere — the JWT itself is the only place a session token "lives"; the server holds no session-token blacklist or store.

### 3.4 Token verification (every authenticated request)

Two FastAPI dependencies, both in `app/api/v1/auth.py`, both built on the same `verify_token`:

```mermaid
flowchart TD
    A["HTTPBearer() extracts raw bearer credentials"] --> B["sanitize_string(credentials.credentials)"]
    B --> C["utils/auth.py: verify_token(token)"]
    C --> D{"token falsy or not str?"}
    D -- yes --> D1["raise ValueError → 422 Invalid token format"]
    D -- no --> E{"regex matches JWT shape (3 dot-separated base64url segments)?"}
    E -- no --> D1
    E -- yes --> F["jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])"]
    F --> G{"JWTError (bad signature / expired / malformed)?"}
    G -- yes --> H["log token_verification_failed → return None"]
    G -- no --> I["return payload['sub']"]
    H --> J{"get_current_user or get_current_session?"}
    I --> J
    J -- "user, sub is None" --> K1["401 Invalid authentication credentials"]
    J -- "user, sub present" --> K2["db_service.get_user(int(sub))"]
    K2 --> K3{"found?"}
    K3 -- no --> K4["404 User not found"]
    K3 -- yes --> K5["bind_context(user_id=user.id) → return User"]
    J -- "session, sub is None" --> L1["401 Invalid authentication credentials"]
    J -- "session, sub present" --> L2["sanitize_string(sub); db_service.get_session(sub)"]
    L2 --> L3{"found?"}
    L3 -- no --> L4["404 Session not found"]
    L3 -- yes --> L5["bind_context(user_id=session.user_id) → return Session"]
```

`get_current_user` and `get_current_session` are structurally identical — they differ only in whether the `sub` claim is looked up against the `user` table (`db_service.get_user`) or the `session` table (`db_service.get_session`). This is also *why* a user token cannot be used on a chat endpoint and vice versa: the `sub` value simply won't resolve in the other table.

### 3.5 JWT internals — exactly how a token is created and checked

Both directions live entirely in `app/utils/auth.py` (21 lines of actual logic):

**Creation — `create_access_token(thread_id, expires_delta=None)`**
```python
expire = datetime.now(UTC) + (expires_delta or timedelta(days=settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS))
to_encode = {
    "sub": thread_id,                                              # user id (as str) OR session UUID (as str)
    "exp": expire,                                                 # standard JWT expiry claim
    "iat": datetime.now(UTC),                                      # issued-at
    "jti": sanitize_string(f"{thread_id}-{datetime.now(UTC).timestamp()}"),  # unique-ish token id, not tracked server-side
}
encoded = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)  # HS256 by default
```
`thread_id` is the **only** thing that differs between a "user token" and a "session token" — the function itself has no concept of token type. `create_access_token` is called from exactly 5 places: `register_user`, `login`, `create_session`, `update_session_name`, `get_user_sessions` (one per list item).

**Verification — `verify_token(token) -> Optional[str]`**
```python
if not token or not isinstance(token, str):
    raise ValueError(...)
if not re.match(r"^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$", token):
    raise ValueError(...)               # structural check before ever touching jose
try:
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    return payload.get("sub")           # signature + exp are verified by jose internally; expired/bad-sig → JWTError
except JWTError:
    return None
```
There is **no separate refresh-token mechanism** — when a token expires, the client must call `/login` (for a user token) or `/auth/session` (for a session token) again. There is also no server-side revocation list: a leaked token remains valid until `exp`, and `JWT_SECRET_KEY` is the single point of trust for every token in the system (rotating it invalidates *all* outstanding tokens at once).

`LoggingContextMiddleware` (§2) independently calls `jwt.decode` a second time, purely to populate log context — it duplicates the decode logic rather than calling `verify_token`, and it never raises on failure.

---

## 4. Chat turn — `POST /chatbot/chat`

`app/api/v1/chatbot.py:chat`, after `get_current_session` (§3.4) has resolved a `Session`.

```mermaid
flowchart TD
    A["chat(request, chat_request: ChatRequest, session)"] --> B{"SESSION_NAMING_ENABLED and session.name == ''?"}
    B -- yes --> C["session_naming.py: maybe_name_session(session.id, session.name, messages)"]
    C --> C1{"_claim_session() wins the race (UPDATE ... WHERE name='')?"}
    C1 -- yes --> C2["asyncio.create_task(_persist_session_name(...))  — fire-and-forget, does not block this request"]
    C1 -- no --> C3["another request already claimed it — skip"]
    B -- no --> D
    C2 --> D
    C3 --> D
    D["agent.get_response(messages, session.id, user_id=session.user_id, username=session.username)"] --> E["§6: graph loop runs to completion"]
    E --> F["ChatResponse(messages=result)"]
    F --> G["200 response"]
    D -.->|"Exception"| H["logger.exception('chat_request_failed') → HTTPException(500)"]
```

`_persist_session_name` (§ session_naming.py:25-39) itself makes a **second, independent LLM call** (`llm_service.call(..., model_name="gpt-5-nano", response_format=SessionTitle)`) that goes through the exact same retry/fallback machinery described in §7 — it just runs in the background and its failure is swallowed (only a metric + log, no user-facing effect).

---

## 5. Streaming chat turn — `POST /chatbot/chat/stream`

`app/api/v1/chatbot.py:chat_stream`. Session-naming branch is identical to §4; the difference is everything downstream of the agent call.

```mermaid
flowchart TD
    A["chat_stream(...)"] --> B["(same session-naming branch as §4)"]
    B --> C["event_generator() — async generator, wrapped in llm_stream_duration_seconds.time()"]
    C --> D["agent.get_stream_response(messages, session.id, user_id, username)"]
    D --> E["§6 graph.astream(..., stream_mode='messages')"]
    E --> F{"yielded item is AIMessage/AIMessageChunk?"}
    F -- no (e.g. ToolMessage) --> G["skip, continue loop"]
    F -- yes --> H["extract_text_content(token.content)"]
    H --> I{"non-empty text?"}
    I -- no --> G
    I -- yes --> J["yield f'data: {StreamResponse(content=text, done=False)}\\n\\n'"]
    J --> G
    G --> K{"stream exhausted?"}
    K -- no --> F
    K -- yes --> L{"graph left an interrupt pending (state.next)?"}
    L -- yes --> M["yield interrupt question as one final chunk"]
    L -- no --> N["asyncio.create_task(memory_service.add(...))  — background"]
    M --> O["yield StreamResponse(content='', done=True)"]
    N --> O
    O --> P["StreamingResponse(event_generator(), media_type='text/event-stream')"]
    C -.->|"any Exception inside generator"| Q["yield StreamResponse(content=str(e), done=True) — error surfaced as a normal SSE chunk, HTTP status stays 200"]
```

---

## 6. The chat ⇄ tool_call graph loop, in detail

This is the shared core called by both §4 and §5, in `LangGraphAgent` (`app/core/langgraph/graph.py`).

```mermaid
flowchart TD
    A["get_response() / get_stream_response()"] --> B["_get_graph()  — lazily calls create_graph() if not yet built"]
    B --> C["_build_config(session_id, user_id, username) → thread_id, Langfuse callback (if enabled), metadata"]
    C --> D["asyncio.gather( graph.aget_state(config), memory_service.search(user_id, last_message.content) )"]
    D --> E{"state.next non-empty? (a previous turn left an ask_human interrupt pending)"}
    E -- yes --> F["graph.ainvoke(Command(resume=last_message.content), config)  — resumes the paused tool_call"]
    E -- no --> G["relevant_memory = memory result or 'No relevant memory found.'"]
    G --> H["graph.ainvoke({messages: dump_messages(messages), long_term_memory: relevant_memory}, config)  — fresh turn, entry point 'chat'"]
    F --> I["graph.aget_state(config) — re-check after invoke"]
    H --> I
    I --> J{"state.next still non-empty? (ask_human fired again this turn)"}
    J -- yes --> K["return interrupt value as the assistant message — turn ends without touching memory_service.add"]
    J -- no --> L["convert_to_openai_messages(response) → asyncio.create_task(memory_service.add(...))  — background"]
    L --> M["__process_messages() → List[Message] returned to the route handler"]
```

Inside the compiled `StateGraph` itself (`create_graph`, `app/core/langgraph/graph.py:125-155`), the two nodes are:

```mermaid
flowchart TD
    start(("entry: chat")) --> CHAT["_chat(state, config)"]
    CHAT --> C1["load_system_prompt(username, long_term_memory=state.long_term_memory)"]
    C1 --> C2["prepare_messages(state.messages, system_prompt) — trims history to MAX_TOKENS via tiktoken, prepends system message"]
    C2 --> C3["llm_service.call(dump_messages(messages))  — §7"]
    C3 --> C4["process_llm_response(response) — normalizes content blocks to a plain string"]
    C4 --> C5{"response is AIMessage AND has tool_calls?"}
    C5 -- yes --> TOOL["goto: tool_call"]
    C5 -- no --> END(("goto: END — turn complete"))
    TOOL --> T1["_tool_call(state)"]
    T1 --> T2["tool_calls = state.messages[-1].tool_calls"]
    T2 --> T3{"len(tool_calls) == 1?"}
    T3 -- yes --> T4["await tools_by_name[name].ainvoke(args)  — §8, single call"]
    T3 -- no --> T5["asyncio.gather(*[ainvoke each]) — §8, parallel calls"]
    T4 --> T6["wrap each result in ToolMessage(content, name, tool_call_id)"]
    T5 --> T6
    T6 --> CHAT2(("goto: chat — loop continues with tool results appended"))
    CHAT2 -.-> CHAT
```

`tool_call` is registered with `RetryPolicy(max_attempts=3)` (`graph.py:132`) — a raised exception inside `_tool_call` itself (not inside an individual tool call, which already catches its own exceptions — see §8) is retried by LangGraph up to 3 times before the graph run fails.

---

## 7. LLM call: retry + circular fallback

Every `llm_service.call(...)` (`app/services/llm/service.py`) — whether from the main chat node or from `_persist_session_name` — goes through the same two-layer resilience wrapper:

```mermaid
flowchart TD
    A["LLMService.call(messages, model_name=None, response_format=None, **kwargs)"] --> B["asyncio.wait_for(_call_with_fallback(...), timeout=LLM_TOTAL_TIMEOUT)"]
    B --> C{"model_name or response_format or kwargs given?"}
    C -- yes --> D["start = index of model_name (or current index); get_target = _override_target (fresh ChatOpenAI + .with_structured_output if response_format); advance wraps circularly (idx+1) % total"]
    C -- no --> E["start = current_model_index; get_target = _default_target (self._llm, already tool-bound); advance = _default_advance (calls _switch_to_next_model())"]
    D --> F["_fallback_loop(messages, start, get_target, advance)"]
    E --> F
    F --> G["for models_tried in 1..total: try _invoke_with_retry(get_target(current), messages)"]
    G --> H{"success?"}
    H -- yes --> I["return result"]
    H -- no: OpenAIError --> J{"models_tried >= total?"}
    J -- yes --> K["raise RuntimeError('failed after trying N models')"]
    J -- no --> L["current = advance(current)"]
    L --> M{"advance returned None?"}
    M -- yes --> K
    M -- no --> G
    B -.->|"asyncio.TimeoutError (whole budget exceeded)"| N["raise RuntimeError('llm call timed out after LLM_TOTAL_TIMEOUT s')"]
```

`_invoke_with_retry` (`service.py:82-96`) is itself a `tenacity`-decorated function: up to `MAX_LLM_CALL_RETRIES` attempts, exponential backoff (2s→10s), retried only on `RateLimitError | APITimeoutError | APIError` — any other `OpenAIError` propagates immediately to the fallback loop, which then switches models instead of retrying the same one.

Model order (circular fallback sequence) is fixed in `app/services/llm/registry.py:LLMRegistry.LLMS`: **`gpt-5-mini` → `gpt-5` → `gpt-5-nano` → (wraps back to `gpt-5-mini`)**.

---

## 8. Tool execution branches

Each tool called from `_tool_call` (§6) is independent and catches its own errors — a failing tool returns an error *string* to the model rather than raising, so one bad tool call never crashes the turn.

```mermaid
flowchart TD
    A["tools_by_name[name].ainvoke(args)"] --> B{"which tool?"}
    B -- duckduckgo_search --> C["DuckDuckGoSearchResults.ainvoke — general web search, handle_tool_error=True"]
    B -- ask_human --> D["interrupt(question) — raises GraphInterrupt, graph run pauses; caught in §6's get_response/get_stream_response"]
    B -- search_products --> E["acumatica_product.py: search_products(query, category, max_results)"]
    B -- search_sales --> F["acumatica_sales.py: search_sales(query, ..., max_results)"]
    E --> E1["build_odata_string_filter(DESCRIPTION_FIELD, query) + optional CATEGORY_FIELD eq filter"]
    E1 --> E2["acumatica_client.query_gi(gi_name=ACUMATICA_PRODUCTS_GI, odata_filter, top=max_results) — §9"]
    E2 --> E3{"raised AcumaticaError / other Exception?"}
    E3 -- yes --> E4["acumatica_tool_calls_total{status=error}.inc(); return 'Product lookup failed: {e}'"]
    E3 -- no --> E5["acumatica_tool_calls_total{status=success}.inc(); return rows_to_compact_json(rows, max_rows)"]
    F --> F1["(mirror of E1-E5 against ACUMATICA_SALES_GI)"]
```

---

## 9. Acumatica session-cookie lifecycle

`AcumaticaClient.query_gi` (`app/services/acumatica.py:71-125`) — shared by both `search_products` and `search_sales`.

```mermaid
flowchart TD
    A["query_gi(gi_name, odata_filter, select, top)"] --> B{"ACUMATICA_BASE_URL configured?"}
    B -- no --> B1["raise AcumaticaError('Acumatica is not configured...')"]
    B -- yes --> C["_get_session_cookie(force_refresh=False)"]
    C --> D["cache_service.get('acumatica:session_cookie')"]
    D --> E{"cache hit?"}
    E -- yes --> F["return cached cookie"]
    E -- no --> G["_login() — POST /entity/auth/login with name/password/company/branch"]
    G --> H["cache_service.set(key, cookie_header, ttl=ACUMATICA_SESSION_TTL_SECONDS)"]
    H --> F
    F --> I["GET {base_url}/odata/{gi_name}?$top&$filter&$select, header Cookie: <cookie>"]
    I --> J{"status == 401?"}
    J -- yes --> K["_get_session_cookie(force_refresh=True) → forces _login() again"]
    K --> L["retry the same GET once with the fresh cookie"]
    J -- no --> M
    L --> M{"status == 200?"}
    M -- no --> M1["log acumatica_gi_query_failed → raise AcumaticaError"]
    M -- yes --> N["rows = resp.json()['value'] (or the raw list) → return rows"]
```

The whole `query_gi` call is additionally wrapped in a tenacity `@retry(stop_after_attempt(2), wait_exponential(...))` (`acumatica.py:70`) — so a transient network failure gets one extra full retry (including a fresh login if needed) on top of the 401-refresh-and-retry shown above.

---

## 10. Long-term memory read/write

`MemoryService` (`app/services/memory.py`) wraps `mem0.AsyncMemory` with a cache layer.

```mermaid
flowchart TD
    subgraph search["memory_service.search(user_id, query) — called before every turn (§6)"]
        S1["user_id is None?"] -- yes --> S2["return '' immediately — anonymous sessions never touch mem0"]
        S1 -- no --> S3["cache_key('memory', user_id, query) — sha256-based deterministic key"]
        S3 --> S4["cache_service.get(key)"]
        S4 --> S5{"cache hit?"}
        S5 -- yes --> S6["return cached string"]
        S5 -- no --> S7["_get_memory() → memory.search(user_id, query) against pgvector"]
        S7 --> S8["join results as '* {memory}' bullet lines"]
        S8 --> S9{"non-empty result?"}
        S9 -- yes --> S10["cache_service.set(key, result) — TTL = CACHE_TTL_SECONDS"]
        S9 -- no --> S11["skip caching an empty result"]
        S10 --> S12["return result"]
        S11 --> S12
        S7 -.->|"Exception"| S13["log failed_to_get_relevant_memory → return ''"]
    end
    subgraph add["memory_service.add(user_id, openai_messages, metadata) — fire-and-forget after every turn (§6)"]
        A1["user_id is None?"] -- yes --> A2["return — nothing persisted"]
        A1 -- no --> A3["_get_memory() → memory.add(messages, user_id, metadata) — mem0 extracts/updates facts in pgvector"]
        A3 -.->|"Exception"| A4["log failed_to_update_long_term_memory — swallowed, turn already returned to the client"]
    end
```

`_get_memory()` lazily constructs the single shared `AsyncMemory` instance on first use (or reuses the one built by `memory_service.initialize()` at startup, §1) — same instance for every user, differentiated only by the `user_id` argument passed into `search`/`add`.

---

## 11. Fetch / clear history

`GET /chatbot/messages` and `DELETE /chatbot/messages` (`app/api/v1/chatbot.py`), both behind `get_current_session` (§3.4):

```mermaid
flowchart TD
    subgraph get["GET /messages"]
        A1["get_session_messages(session)"] --> A2["agent.get_chat_history(session.id)"]
        A2 --> A3["graph.aget_state({configurable: {thread_id: session.id}})"]
        A3 --> A4{"state.values has 'messages'?"}
        A4 -- no --> A5["return []"]
        A4 -- yes --> A6["__process_messages() — convert_to_openai_messages, keep only user/assistant with non-empty content"]
    end
    subgraph clear["DELETE /messages"]
        B1["clear_chat_history(session)"] --> B2["agent.clear_chat_history(session.id)"]
        B2 --> B3["_get_connection_pool()"]
        B3 --> B4["for table in CHECKPOINT_TABLES (checkpoints, checkpoint_writes, checkpoint_blobs): DELETE ... WHERE thread_id = session.id, inside one pipeline"]
    end
```

Note `clear_chat_history` deletes **checkpoint** rows only — it does not touch `memory_service` (mem0/pgvector long-term memory survives clearing a session's chat history, by design: long-term memory is per-user, not per-session).

---

## 12. Function index (file:line)

| Function | File |
|---|---|
| `lifespan`, `root`, `health_check`, `validation_exception_handler` | `app/main.py` |
| `register_user`, `login`, `create_session`, `delete_session`, `update_session_name`, `get_user_sessions`, `get_current_user`, `get_current_session` | `app/api/v1/auth.py` |
| `chat`, `chat_stream`, `get_session_messages`, `clear_chat_history` (route) | `app/api/v1/chatbot.py` |
| `create_access_token`, `verify_token` | `app/utils/auth.py` |
| `sanitize_string`, `sanitize_email`, `sanitize_dict`, `sanitize_list`, `validate_password_strength` | `app/utils/sanitization.py` |
| `User.hash_password`, `User.verify_password` | `app/models/user.py` |
| `MetricsMiddleware`, `LoggingContextMiddleware`, `ProfilingMiddleware` | `app/core/middleware.py` |
| `bind_context`, `clear_context`, `get_context`, `setup_logging` | `app/core/logging.py` |
| `langfuse_init`, `get_langfuse_callback_handler` | `app/core/observability.py` |
| `LangGraphAgent.{_chat,_tool_call,create_graph,get_response,get_stream_response,get_chat_history,clear_chat_history,__process_messages,_build_config,_get_connection_pool,_get_graph}` | `app/core/langgraph/graph.py` |
| `load_system_prompt` | `app/core/prompts/__init__.py` |
| `dump_messages`, `prepare_messages`, `process_llm_response`, `extract_text_content` | `app/utils/graph.py` |
| `LLMService.{call,_call_with_fallback,_fallback_loop,_invoke_with_retry,_switch_to_next_model,bind_tools,get_llm}` | `app/services/llm/service.py` |
| `LLMRegistry.{get,get_all_names,get_model_at_index}` | `app/services/llm/registry.py` |
| `maybe_name_session`, `_claim_session`, `_persist_session_name`, `_build_placeholder` | `app/services/session_naming.py` |
| `AcumaticaClient.{_login,_get_session_cookie,query_gi}`, `build_odata_string_filter`, `rows_to_compact_json` | `app/services/acumatica.py` |
| `search_products` | `app/core/langgraph/tools/acumatica_product.py` |
| `search_sales` | `app/core/langgraph/tools/acumatica_sales.py` |
| `ask_human` | `app/core/langgraph/tools/ask_human.py` |
| `duckduckgo_search_tool` | `app/core/langgraph/tools/duckduckgo_search.py` |
| `MemoryService.{search,add,initialize,_get_memory}` | `app/services/memory.py` |
| `InMemoryCacheService`, `ValkeyCacheService`, `cache_key`, `_create_cache_service` | `app/core/cache.py` |
| `DatabaseService.{create_user,get_user,get_user_by_email,create_session,delete_session,get_session,get_user_sessions,update_session_name,health_check}` | `app/services/database.py` |
| `limiter` (slowapi instance) | `app/core/limiter.py` |
