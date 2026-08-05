"""User message
    ↓
Retrieve chat state + long-term memory
    ↓
Send messages to LLM
    ↓
Did the LLM request a tool?
    ├── No → Return answer
    └── Yes → Execute tool
                   ↓
              Send tool result to LLM
                   ↓
              Repeat until final answer
    ↓
Save conversation to long-term memory"""

# LangGraph agent: chat <-> tool_call loop with Postgres checkpointing.

import asyncio
from typing import AsyncGenerator, Optional, cast
from urllib.parse import quote_plus

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage, convert_to_openai_messages
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, StateGraph
from langgraph.graph.state import Command, CompiledStateGraph
from langgraph.types import RetryPolicy, StateSnapshot
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import Environment, settings
from app.core.langgraph.tools import tools
from app.core.logging import logger
from app.core.metrics import llm_inference_duration_seconds
from app.core.observability import langfuse_callback_handler
from app.core.prompts import load_system_prompt
from app.schemas import GraphState, Message
from app.services.llm import llm_service
from app.services.memory import memory_service
from app.utils import dump_messages, extract_text_content, prepare_messages, process_llm_response

PostgresConnPool = AsyncConnectionPool[AsyncConnection[DictRow]]


class LangGraphAgent:
    """Owns the compiled graph, connection pool, and public chat API."""

    def __init__(self):
        self.llm_service = llm_service
        self.llm_service.bind_tools(tools)
        self.tools_by_name = {tool.name: tool for tool in tools}
        self._connection_pool: Optional[PostgresConnPool] = None
        self._graph: Optional[CompiledStateGraph] = None
        logger.info("langgraph_agent_initialized", model=settings.DEFAULT_LLM_MODEL)

    async def _get_connection_pool(self) -> Optional[PostgresConnPool]:
        if self._connection_pool is None:
            try:
                connection_url = (
                    f"postgresql://{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
                    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
                )
                self._connection_pool = AsyncConnectionPool(
                    connection_url,
                    open=False,
                    max_size=settings.POSTGRES_POOL_SIZE,
                    kwargs={
                        "autocommit": True,
                        "connect_timeout": 5,
                        "prepare_threshold": None,
                        "row_factory": dict_row,
                    },
                )
                await self._connection_pool.open()
                logger.info("connection_pool_created")
            except Exception as e:
                logger.error("connection_pool_creation_failed", error=str(e))
                if settings.ENVIRONMENT == Environment.PRODUCTION:
                    return None
                raise
        return self._connection_pool

    async def _chat(self, state: GraphState, config: RunnableConfig) -> Command:
        current_llm = self.llm_service.get_llm()
        model_name = (
            current_llm.model_name
            if current_llm and hasattr(current_llm, "model_name")
            else settings.DEFAULT_LLM_MODEL
        )

        username = config.get("metadata", {}).get("username")
        thread_id = config.get("configurable", {}).get("thread_id")
        system_prompt = load_system_prompt(username=username, long_term_memory=state.long_term_memory)
        messages = prepare_messages(state.messages, system_prompt)

        try:
            with llm_inference_duration_seconds.labels(model=model_name).time():
                response_message = await self.llm_service.call(dump_messages(messages))
            response_message = process_llm_response(response_message)

            goto = "tool_call" if isinstance(response_message, AIMessage) and response_message.tool_calls else END
            return Command(update={"messages": [response_message]}, goto=goto)
        except Exception as e:
            logger.error("llm_call_failed_all_models", session_id=thread_id, error=str(e))
            raise Exception(f"failed to get llm response after trying all models: {e}") from e

    async def _tool_call(self, state: GraphState) -> Command:
        tool_calls = state.messages[-1].tool_calls

        async def _execute_tool(tool_call: dict) -> ToolMessage:
            tool_result = await self.tools_by_name[tool_call["name"]].ainvoke(tool_call["args"])
            return ToolMessage(content=tool_result, name=tool_call["name"], tool_call_id=tool_call["id"])

        if len(tool_calls) == 1:
            outputs = [await _execute_tool(tool_calls[0])]
        else:
            outputs = list(await asyncio.gather(*[_execute_tool(tc) for tc in tool_calls]))

        return Command(update={"messages": outputs}, goto="chat")

    async def create_graph(self) -> Optional[CompiledStateGraph]:
        """Build and compile the state graph, attaching the Postgres checkpointer."""
        if self._graph is None:
            try:
                graph_builder = StateGraph(GraphState)
                graph_builder.add_node("chat", self._chat, destinations=("tool_call", END))
                graph_builder.add_node(
                    "tool_call", self._tool_call, destinations=("chat",), retry_policy=RetryPolicy(max_attempts=3)
                )
                graph_builder.set_entry_point("chat")
                graph_builder.set_finish_point("chat")

                connection_pool = await self._get_connection_pool()
                if connection_pool:
                    checkpointer = AsyncPostgresSaver(connection_pool)
                    await checkpointer.setup()
                else:
                    checkpointer = None
                    if settings.ENVIRONMENT != Environment.PRODUCTION:
                        raise Exception("Connection pool initialization failed")

                self._graph = graph_builder.compile(
                    checkpointer=checkpointer, name=f"{settings.PROJECT_NAME} Agent ({settings.ENVIRONMENT.value})"
                )
                logger.info("graph_created", has_checkpointer=checkpointer is not None)
            except Exception as e:
                logger.error("graph_creation_failed", error=str(e))
                if settings.ENVIRONMENT == Environment.PRODUCTION:
                    return None
                raise
        return self._graph

    async def _get_graph(self) -> CompiledStateGraph:
        if self._graph is None:
            self._graph = await self.create_graph()
        if self._graph is None:
            raise RuntimeError("graph initialization failed")
        return self._graph

    def _build_config(self, session_id: str, user_id: Optional[str], username: Optional[str]) -> RunnableConfig:
        callbacks: list[BaseCallbackHandler] = [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else []
        return {
            "configurable": {"thread_id": session_id},
            "callbacks": callbacks,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
            },
        }

    async def get_response(
        self, messages: list[Message], session_id: str, user_id: Optional[str] = None, username: Optional[str] = None
    ) -> list[Message]:
        """Run one full turn and return the resulting assistant/user message list."""
        graph = await self._get_graph()
        config = self._build_config(session_id, user_id, username)

        try:
            state, relevant_memory = await asyncio.gather(
                graph.aget_state(config), memory_service.search(user_id, messages[-1].content)
            )

            if state.next:
                logger.info("resuming_interrupted_graph", session_id=session_id)
                response = await graph.ainvoke(Command(resume=messages[-1].content), config=config)
            else:
                relevant_memory = relevant_memory or "No relevant memory found."
                response = await graph.ainvoke(
                    input={"messages": dump_messages(messages), "long_term_memory": relevant_memory}, config=config
                )

            state = await graph.aget_state(config)
            if state.next:
                interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
                return [Message(role="assistant", content=str(interrupt_value))]

            openai_msgs = cast(list[dict], convert_to_openai_messages(response["messages"]))
            asyncio.create_task(memory_service.add(user_id, openai_msgs, config.get("metadata")))
            return self.__process_messages(response["messages"])
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
            return [Message(role="assistant", content=str(interrupt_value))]
        except Exception as e:
            logger.exception("get_response_failed", error=str(e), session_id=session_id)
            raise

    async def get_stream_response(
        self, messages: list[Message], session_id: str, user_id: Optional[str] = None, username: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens for one turn."""
        config = self._build_config(session_id, user_id, username)
        graph = await self._get_graph()

        try:
            state, relevant_memory = await asyncio.gather(
                graph.aget_state(config), memory_service.search(user_id, messages[-1].content)
            )

            if state.next:
                graph_input = Command(resume=messages[-1].content)
            else:
                relevant_memory = relevant_memory or "No relevant memory found."
                graph_input = {"messages": dump_messages(messages), "long_term_memory": relevant_memory}

            async for token, _ in graph.astream(graph_input, config, stream_mode="messages"):
                if not isinstance(token, (AIMessage, AIMessageChunk)):
                    continue
                text = extract_text_content(token.content)
                if text:
                    yield text

            state = await graph.aget_state(config)
            if state.next:
                interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
                yield str(interrupt_value)
            elif state.values and "messages" in state.values:
                openai_msgs = cast(list[dict], convert_to_openai_messages(state.values["messages"]))
                asyncio.create_task(memory_service.add(user_id, openai_msgs, config.get("metadata")))
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
            yield str(interrupt_value)
        except Exception as e:
            logger.exception("stream_processing_failed", error=str(e), session_id=session_id)
            raise

    async def get_chat_history(self, session_id: str) -> list[Message]:
        """Return the full message history for a session."""
        graph = await self._get_graph()
        state: StateSnapshot = await graph.aget_state(config={"configurable": {"thread_id": session_id}})
        return self.__process_messages(state.values["messages"]) if state.values else []

    def __process_messages(self, messages: list[BaseMessage]) -> list[Message]:
        openai_style = convert_to_openai_messages(messages)
        return [
            Message(role=m["role"], content=str(m["content"]))
            for m in openai_style
            if m["role"] in ["assistant", "user"] and m["content"]
        ]

    async def clear_chat_history(self, session_id: str) -> None:
        """Delete all checkpoint rows for a session."""
        conn_pool = await self._get_connection_pool()
        if conn_pool is None:
            raise RuntimeError("connection pool unavailable; cannot clear chat history")
        async with conn_pool.connection() as conn:
            async with conn.pipeline():
                for table in settings.CHECKPOINT_TABLES:
                    await conn.execute(
                        sql.SQL("DELETE FROM {} WHERE thread_id = %s").format(sql.Identifier(table)), (session_id,)
                    )
        logger.info("checkpoint_tables_cleared_for_session", session_id=session_id)
