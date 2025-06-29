

import logging
from typing import List, Optional, Callable, Dict
from telegram.ext import ContextTypes

# --------------------------------------------------------------------------- #
#  Logging                                                                    #
# --------------------------------------------------------------------------- #
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# --------------------------------------------------------------------------- #
#  Keys                                                                       #
# --------------------------------------------------------------------------- #
STATE_STACK_KEY  = "state_stack"
CUR_STATE_KEY    = "current_state"
LEGACY_STATE_KEY = "state"  # for backward-compatibility

# --------------------------------------------------------------------------- #
#  Helper                                                                     #
# --------------------------------------------------------------------------- #
def _sync_alias(context: ContextTypes.DEFAULT_TYPE, value: Optional[str]) -> None:
    """
    Keep the old 'state' key in sync for legacy code.
    """
    if value is None:
        context.user_data.pop(LEGACY_STATE_KEY, None)
    else:
        context.user_data[LEGACY_STATE_KEY] = value

# --------------------------------------------------------------------------- #
#  API                                                                        #
# --------------------------------------------------------------------------- #
def push_state(context: ContextTypes.DEFAULT_TYPE, state: str) -> None:
    """
    Pushes a new state onto the stack (unless identical to current),
    updates current_state and legacy alias.
    """
    stack: List[str] = context.user_data.setdefault(STATE_STACK_KEY, [])
    top = stack[-1] if stack else None
    if top != state:
        stack.append(state)
        logger.debug(f"PUSH_STATE: '{state}' added to stack.")
    else:
        logger.debug(f"PUSH_STATE: '{state}' is already on top; skipping.")

    context.user_data[CUR_STATE_KEY] = stack[-1]
    _sync_alias(context, stack[-1])
    logger.debug(f"STACK AFTER PUSH: {stack}")
    logger.debug(f"CURRENT_STATE: {stack[-1]}")


def pop_state(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """
    Pops the top state from the stack, returns new current_state (or None).
    """
    stack: List[str] = context.user_data.get(STATE_STACK_KEY, [])
    if not stack:
        logger.debug("POP_STATE: stack empty; nothing to pop.")
        context.user_data.pop(CUR_STATE_KEY, None)
        _sync_alias(context, None)
        return None

    popped = stack.pop()
    logger.debug(f"POP_STATE: '{popped}' removed.")
    prev = stack[-1] if stack else None
    if prev:
        context.user_data[CUR_STATE_KEY] = prev
    else:
        context.user_data.pop(CUR_STATE_KEY, None)
    _sync_alias(context, prev)
    logger.debug(f"STACK AFTER POP: {stack}")
    logger.debug(f"CURRENT_STATE: {prev}")
    return prev


def reset_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Clears the entire state stack and related keys.
    """
    context.user_data.pop(STATE_STACK_KEY, None)
    context.user_data.pop(CUR_STATE_KEY, None)
    context.user_data.pop(LEGACY_STATE_KEY, None)
    logger.debug("RESET_STATE: all state keys cleared.")


def get_current_state(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """
    Returns the current active state (or None).
    """
    return context.user_data.get(CUR_STATE_KEY)
