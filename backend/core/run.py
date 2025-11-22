"""
This module represents the modernized, streamlined core of the agent execution pipeline.

It replaces the complex, class-based system of the old `run.py` with a single, elegant,
and data-driven `run_agent` function. This new architecture is built entirely on the
plugin-based tool discovery system, making it incredibly modular and extensible.
"""

import json
import asyncio
from typing import Dict, Any, AsyncGenerator

# Local imports
from core.utils.logger import logger
from core.utils import tool_discovery
from core.services.llm import LlmService
from core.services.supabase import DBConnection

# --- System Prompt Construction ---

def _build_system_prompt(agent_config: Dict[str, Any]) -> str:
    """
    Constructs the system prompt for the LLM, including tool definitions.
    """
    # Start with the base prompt from the agent's configuration or a default.
    system_prompt = agent_config.get("system_prompt", "You are a helpful assistant.")

    # Get metadata for all discovered tools.
    tools_metadata = tool_discovery.get_tools_metadata()

    if not tools_metadata:
        return system_prompt # No tools to add

    # Format the tool metadata for the LLM.
    formatted_tools = json.dumps(tools_metadata, indent=2)
    tool_prompt = f"""\n\n--- AVAILABLE TOOLS ---\n
You have access to the following tools. Respond with a JSON object in a <tool_code> block to use a tool.

Example:
<tool_code>
{{
  "tool_name": "example_tool_name",
  "parameters": {{
    "param1": "value1",
    "param2": "value2"
  }}
}}
</tool_code>

Available Tools Schema:
{formatted_tools}
"""

    return system_prompt + tool_prompt

# --- Main Agent Execution Logic ---

async def run_agent(
    thread_id: str,
    model_name: str,
    agent_config: Dict[str, Any],
    cancellation_event: asyncio.Event = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    The core async generator for running an agent.

    This function orchestrates the conversation with the LLM, including message
    history management, tool discovery, tool execution, and streaming responses.
    """
    logger.info(f"Starting agent run for thread {thread_id} with model {model_name}")
    db = await DBConnection().client
    llm_service = LlmService()

    # 1. Fetch conversation history
    messages_query = await db.table('messages').select('*').eq('thread_id', thread_id).order('created_at').execute()
    messages = [msg['content'] for msg in messages_query.data]

    # 2. Build the system prompt with discovered tools
    system_prompt = _build_system_prompt(agent_config)
    messages.insert(0, {"role": "system", "content": system_prompt})

    # 3. Main execution loop
    while not (cancellation_event and cancellation_event.is_set()):
        yield {"type": "status", "status": "thinking"}

        # 4. Call the LLM with the current conversation history
        llm_response = await llm_service.chat_completion(model=model_name, messages=messages, stream=True)

        full_response_content = ""
        tool_code_block = None

        async for chunk in llm_response:
            if not chunk or not chunk.choices:
                continue
            
            delta = chunk.choices[0].delta.content or ""
            full_response_content += delta
            yield {"type": "assistant_chunk", "content": delta}

            # Simple parsing for the <tool_code> block
            if "<tool_code>" in full_response_content and "</tool_code>" in full_response_content:
                start = full_response_content.find("<tool_code>") + len("<tool_code>")
                end = full_response_content.find("</tool_code>")
                tool_code_str = full_response_content[start:end].strip()
                try:
                    tool_code_block = json.loads(tool_code_str)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON in <tool_code> block.")
                break # Stop processing the stream once a tool call is found

        # 5. Add the full assistant message to history
        messages.append({"role": "assistant", "content": full_response_content})
        await db.table('messages').insert({"thread_id": thread_id, "type": "assistant", "content": {"role": "assistant", "content": full_response_content}}).execute()

        # 6. If a tool was called, execute it
        if tool_code_block:
            tool_name = tool_code_block.get("tool_name")
            parameters = tool_code_block.get("parameters", {})
            tool = tool_discovery.get_tool(tool_name)

            if not tool:
                error_message = f"Tool '{tool_name}' not found."
                yield {"type": "tool_output", "tool_name": tool_name, "output": {"error": error_message}, "is_error": True}
                messages.append({"role": "tool", "content": json.dumps({"error": error_message})})
                continue

            yield {"type": "status", "status": f"Executing tool: {tool_name}"}
            try:
                # Execute the tool and get the structured output
                tool_output = await tool.execute(**parameters)
                
                # Send the structured output to the stream
                yield {"type": "tool_output", "tool_name": tool_name, "output": tool_output}
                
                # Add the stringified output to the message history for the next LLM turn
                messages.append({"role": "tool", "content": json.dumps(tool_output)})
                await db.table('messages').insert({"thread_id": thread_id, "type": "tool", "content": {"tool_name": tool_name, "output": tool_output}}).execute()

            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
                error_output = {"error": str(e)}
                yield {"type": "tool_output", "tool_name": tool_name, "output": error_output, "is_error": True}
                messages.append({"role": "tool", "content": json.dumps(error_output)})
                continue
        else:
            # If no tool was called, the agent's turn is over.
            break

    yield {"type": "status", "status": "completed"}
    logger.info(f"Agent run for thread {thread_id} completed.")
