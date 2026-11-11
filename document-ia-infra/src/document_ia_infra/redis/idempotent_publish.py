"""Atomic idempotent publication on the execution stream.

A request may only publish while it still owns its idempotency reservation, and
the ownership check, the capacity admission and the XADD must be one operation.
Any separate check leaves a window: the key can expire or be re-acquired while
the publisher awaits its connection, and the stale request then publishes a
second execution. Redis refuses nested EVAL, so the admission body is inlined
here (generated from ADMISSION_SCRIPT, which stays the single source of truth)
inside a Lua function, so its own `return` statements work unchanged.

KEYS[1] reservation.
KEYS[2] execution stream, KEYS[3] webhook stream.
KEYS[4] execution admission state, KEYS[5] webhook admission state.

ARGV[1] execution id, ARGV[2] reservation TTL, then the admission parameters.

Returns {1, message_id} when published, {0} when the reservation is not ours,
{-1} when asynchronous capacity is exhausted.
"""

import re

from document_ia_infra.redis.admission import ADMISSION_SCRIPT

_ADMISSION_KEY_SHIFT = 1
_ADMISSION_ARG_SHIFT = 2

_SHIFTS = {"KEYS": _ADMISSION_KEY_SHIFT, "ARGV": _ADMISSION_ARG_SHIFT}

# Every reference form the admission script may use. An unhandled shape must
# fail loudly: a silently unshifted reference reads or writes the wrong key or
# argument, corrupting behaviour with no error at all.
_LITERAL_INDEX = re.compile(r"\b(KEYS|ARGV)\[(\d+)\]")
_RELATIVE_INDEX = re.compile(r"\b(KEYS|ARGV)\[i\]")
_RELATIVE_OFFSET = re.compile(r"\b(KEYS|ARGV)\[i\s*\+\s*(\d+)\]")
# Any other bracket form (`KEYS[#KEYS]`, `ARGV[j]`, ...) cannot be expressed in
# the mapping above, so it must be rejected rather than passed through.
_ANY_REFERENCE = re.compile(r"\b(?:KEYS|ARGV)\[[^\]]*\]")


def _shift_admission_script(admission_script: str) -> str:
    """Rebase the admission script's keys and args onto the combined script.

    The admission script owns KEYS[1..4] and ARGV[1..11]. Here KEYS[1] is the
    reservation, so its keys move by one; ARGV[1..2] are the reservation's, so
    its args move by two.

    Substitution is structural rather than a fixed list of indexes, and the
    result is checked afterwards: any reference still inside the reservation's
    own range means a form the mapping did not anticipate, so this raises rather
    than emitting a subtly wrong script.
    """
    shifted = _LITERAL_INDEX.sub(
        lambda m: f"{m.group(1)}[{int(m.group(2)) + _SHIFTS[m.group(1)]}]",
        admission_script,
    )
    shifted = _RELATIVE_OFFSET.sub(
        lambda m: f"{m.group(1)}[i + {int(m.group(2)) + _SHIFTS[m.group(1)]}]",
        shifted,
    )
    shifted = _RELATIVE_INDEX.sub(
        lambda m: f"{m.group(1)}[i + {_SHIFTS[m.group(1)]}]", shifted
    )
    if _RELATIVE_INDEX.search(shifted):
        raise ValueError("Unhandled relative reference in the admission script")

    unrecognised = {
        match.group(0)
        for match in _ANY_REFERENCE.finditer(shifted)
        if not _LITERAL_INDEX.fullmatch(match.group(0))
        and not _RELATIVE_OFFSET.fullmatch(match.group(0))
    }
    if unrecognised:
        raise ValueError(
            "Unhandled reference form in the admission script: "
            + ", ".join(sorted(unrecognised))
        )

    # Every reference in the shifted body must now sit above the reservation's
    # own range (KEYS[1], ARGV[1..2]); anything still inside it was not shifted
    # and would address the wrong key or argument.
    leftover = {
        match.group(0)
        for match in _LITERAL_INDEX.finditer(shifted)
        if int(match.group(2)) <= _SHIFTS[match.group(1)]
    }
    if leftover:
        raise ValueError(
            "Unshifted reference in the admission script: "
            + ", ".join(sorted(leftover))
        )

    return "\n".join(
        ("    " + line if line.strip() else line)
        for line in shifted.strip("\n").split("\n")
    )


IDEMPOTENT_PUBLISH_TEMPLATE = """\
local reservation = redis.call('GET', KEYS[1])
if not reservation then return {0} end
local ok, entry = pcall(cjson.decode, reservation)
if not ok or entry['execution_id'] ~= ARGV[1] or entry['status'] ~= 'IN_PROGRESS' then
    return {0}
end

local function admit_and_publish()
__ADMISSION_BODY__
end

local admission = admit_and_publish()
if not admission or admission[1] ~= 1 then return {-1} end

-- The execution is accepted: record it while still holding the key, so a retry
-- replays instead of scheduling it a second time.
entry['status'] = 'COMPLETED'
redis.call('SET', KEYS[1], cjson.encode(entry), 'EX', tonumber(ARGV[2]))
return {1, admission[2]}
"""


def build_idempotent_publish_script(admission_script: str) -> str:
    """Inline the admission script into the ownership-fenced publication script.

    Placeholder replacement, not `%` formatting: the Lua body contains `%`
    patterns that `%`-formatting would corrupt.
    """
    body = _shift_admission_script(admission_script)
    return IDEMPOTENT_PUBLISH_TEMPLATE.replace("__ADMISSION_BODY__", body)


IDEMPOTENT_PUBLISH_SCRIPT = build_idempotent_publish_script(ADMISSION_SCRIPT)
