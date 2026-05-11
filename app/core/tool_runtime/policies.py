DEFAULT_AUTO_FOLLOWUP_ENABLED = True
DEFAULT_MAX_FOLLOWUP_ROUNDS = 300


def get_default_tool_loop_policy() -> dict:
    return {
        'auto_followup_enabled': DEFAULT_AUTO_FOLLOWUP_ENABLED,
        'max_followup_rounds': DEFAULT_MAX_FOLLOWUP_ROUNDS,
    }
