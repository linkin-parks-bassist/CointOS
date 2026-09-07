"""Normalize an observed llama.cpp launch into its context-layout facts.

This helper receives an observed native launch command plus backend metadata
facts after caller identity validation. It is pure: no I/O, no globals or
config, no mutation of inputs. It describes the resident pool only
(preallocated context tokens, parallel sequences, per-sequence context); it is
not an inference reservation, and dynamic or unproven modes receive no credit
through it.
"""

_CTX_FLAG = "--ctx-size"
_PARALLEL_FLAG = "--parallel"
_UNIFIED_FLAG = "--kv-unified"
_CAP_FLAG = "--kv-unified-per-slot"

_VALUE_FLAGS = (_CTX_FLAG, _PARALLEL_FLAG, _CAP_FLAG)
_REJECTED_ALIASES = frozenset({"-c", "-np", "-kvu", "--no-kvu", "--no-kv-unified"})
_REJECTED_EQUALS_PREFIXES = (
    "--ctx-size=",
    "--parallel=",
    "--kv-unified=",
    "--kv-unified-per-slot=",
)


def _positive_integer(value):
    return type(value) is int and value > 0


def _positive_decimal(text):
    if not isinstance(text, str) or not text:
        return None
    if not all(char in "0123456789" for char in text):
        return None
    value = int(text)
    return value if value > 0 else None


def _scan_layout_flags(launch_command, total_context, total_slots):
    """Return (unified_count, cap) or None when the launch is malformed.

    Managed flags must appear in the explicit space-separated observed form.
    Every other argument (model path, MTP, batch, priority, ...) is allowed
    untouched.
    """
    ctx_count = 0
    parallel_count = 0
    unified_count = 0
    cap = None
    cap_count = 0
    index = 0
    length = len(launch_command)
    while index < length:
        argument = launch_command[index]
        if any(argument.startswith(prefix)
               for prefix in _REJECTED_EQUALS_PREFIXES):
            return None
        if argument in _REJECTED_ALIASES:
            return None
        if argument == _UNIFIED_FLAG:
            unified_count += 1
            if unified_count > 1:
                return None
            index += 1
        elif argument in _VALUE_FLAGS:
            if index + 1 >= length:
                return None
            value = launch_command[index + 1]
            if argument == _CTX_FLAG:
                ctx_count += 1
                if ctx_count > 1 or value != str(total_context):
                    return None
            elif argument == _PARALLEL_FLAG:
                parallel_count += 1
                if parallel_count > 1 or value != str(total_slots):
                    return None
            else:
                cap_count += 1
                if cap_count > 1:
                    return None
                cap = _positive_decimal(value)
                if cap is None:
                    return None
            index += 2
        else:
            index += 1
    if ctx_count != 1 or parallel_count != 1:
        return None
    if cap_count == 1 and unified_count != 1:
        return None
    return unified_count, cap


def observed_context_layout(launch_command, total_context, total_slots,
                            per_slot_context, trained_context):
    """Normalize observed launch and metadata facts into a layout record.

    Returns None for invalid, contradictory, or unsupported facts. On success
    the record describes the resident pool only: the fixed or shared context
    mode, the backend's total preallocated context tokens, the number of
    parallel sequences, and the context tokens per sequence.
    """
    if not all(_positive_integer(value) for value in (
            total_context, total_slots, per_slot_context, trained_context)):
        return None
    if not isinstance(launch_command, list):
        return None
    if not all(isinstance(argument, str) for argument in launch_command):
        return None

    scanned = _scan_layout_flags(launch_command, total_context, total_slots)
    if scanned is None:
        return None
    unified_count, cap = scanned

    if unified_count == 1:
        if cap is not None:
            if cap > min(total_context, trained_context):
                return None
            if per_slot_context != cap:
                return None
        elif per_slot_context != min(total_context, trained_context):
            return None
        context_mode = "shared"
    else:
        if total_context % total_slots != 0:
            return None
        if per_slot_context != total_context // total_slots:
            return None
        if per_slot_context > trained_context:
            return None
        context_mode = "fixed"

    return {
        "context_mode": context_mode,
        "backend_context_tokens": total_context,
        "parallel_sequences": total_slots,
        "context_tokens_per_sequence": per_slot_context,
        "preallocated_context_tokens": total_context,
    }
