import os
import anthropic
import streamlit as st
from streamlit.logger import get_logger
import time
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4096

logger = get_logger(__name__)


def get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to a `.env` file or export it in your shell before running the app."
        )
        st.stop()
    return anthropic.Anthropic(api_key=api_key, timeout=90.0)


def call_claude_tool(
    system_prompt: str,
    user_prompt: str,
    tool: dict,
    tool_name: str,
    client: anthropic.Anthropic = None,
    max_retries: int = 2,
) -> dict:
    """Call Claude with a forced tool, returning the tool input as a dict."""
    if client is None:
        client = get_client()

    for attempt in range(max_retries):
        logger.info("calling API — tool=%s attempt=%d", tool_name, attempt + 1)
        start = time.perf_counter()
        try:
            print(f"System Prompt:\n{system_prompt}\n\n")
            print(f"User Prompt:\n{user_prompt}\n\n")
            print(f"Tool Name:\n{tool_name}")

            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
            ) as stream:
                events = 0
                for _ in stream:
                    events += 1
                response = stream.get_final_message()

            elapsed = time.perf_counter() - start
            logger.info(
                "done in %.1fs — events=%s stop_reason=%s in_tokens=%s out_tokens=%s",
                elapsed, events, response.stop_reason,
                response.usage.input_tokens, response.usage.output_tokens,
            )

            if response.stop_reason == "max_tokens":
                st.warning("Response hit the token limit and may be incomplete.")

            for block in response.content:
                if block.type == "tool_use" and block.name == tool_name:
                    return block.input

            st.error("Claude did not return the expected structured output.")
            st.stop()

        except anthropic.AuthenticationError:
            st.error("Invalid API key. Check your ANTHROPIC_API_KEY and try again.")
            st.stop()
        except anthropic.RateLimitError:
            st.error("Rate limit reached. Wait a moment and try again.")
            st.stop()
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            elapsed = time.perf_counter() - start
            if attempt < max_retries - 1:
                wait = 20 * (attempt + 1)
                print(f"[retry] timeout after {elapsed:.0f}s on attempt {attempt+1} — waiting {wait}s")
                logger.warning("timeout on attempt %d, retrying in %ds", attempt + 1, wait)
                time.sleep(wait)
            else:
                st.error(
                    f"Request timed out after {max_retries} attempts. "
                    "This usually means the API is under load or rate-limited. "
                    "Wait a minute and try again."
                )
                st.stop()
        except anthropic.APIError as e:
            st.error(f"API error: {e}")
            st.stop()
        except Exception as e:
            logger.exception("Unexpected error calling Claude")
            st.error(f"Unexpected error: {e}")
            st.stop()


def call_claude(system_prompt: str, user_prompt: str) -> str:
    """Plain text completion. Kept for ad-hoc use."""
    client = get_client()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text
    except anthropic.AuthenticationError:
        st.error("Invalid API key. Check your ANTHROPIC_API_KEY and try again.")
        st.stop()
    except anthropic.RateLimitError:
        st.error("Rate limit reached. Wait a moment and try again.")
        st.stop()
    except anthropic.APIError as e:
        st.error(f"API error: {e}")
        st.stop()
    except Exception as e:
        logger.exception("Unexpected error calling Claude")
        st.error(f"Unexpected error: {e}")
        st.stop()


def call_claude_tool_batched(
    system_prompt: str,
    profiles: list,
    prompt_builder_fn,
    tool: dict,
    tool_name: str,
    batch_size: int = 8,
    table_name: str = None,
    dataset_context: str = "",
    inter_batch_delay: float = 1.0,
) -> list:
    """Run call_claude_tool in batches and merge the returned 'fields' arrays.

    Batching keeps output tokens per call small enough to avoid connection drops.
    inter_batch_delay adds a pause between calls to avoid rate-limit queuing.
    """
    client = get_client()
    batches = [profiles[i:i + batch_size] for i in range(0, len(profiles), batch_size)]
    print(f"[batch] {len(profiles)} fields → {len(batches)} batches of {batch_size}")
    all_fields = []
    for i, batch in enumerate(batches):
        if i > 0:
            time.sleep(inter_batch_delay)
        prompt = prompt_builder_fn(batch, table_name=table_name, dataset_context=dataset_context)
        print(f"[batch] calling batch {i+1}/{len(batches)} ({len(batch)} fields)")
        result = call_claude_tool(system_prompt, prompt, tool, tool_name, client=client)
        all_fields.extend(result.get("fields", []))
        print(f"[batch] batch {i+1} done — running total {len(all_fields)} fields")
    return all_fields
