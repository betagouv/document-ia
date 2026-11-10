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

from document_ia_infra.redis.admission import ADMISSION_SCRIPT

_ADMISSION_KEY_SHIFT = 1
_ADMISSION_ARG_SHIFT = 2


def _shift_admission_script(admission_script: str) -> str:
    """Rebase the admission script's keys and args onto the combined script.

    The admission script owns KEYS[1..4] and ARGV[1..11]. Here KEYS[1] is the
    reservation, so its keys move by one; ARGV[1..2] are the reservation's, so
    its args move by two.
    """
    shifted = admission_script
    # Highest indexes first so a shift never rewrites an already-shifted index.
    for index in (4, 3, 2, 1):
        shifted = shifted.replace(
            f"KEYS[{index}]", f"KEYS[{index + _ADMISSION_KEY_SHIFT}]"
        )
    for index in range(11, 0, -1):
        shifted = shifted.replace(
            f"ARGV[{index}]", f"ARGV[{index + _ADMISSION_ARG_SHIFT}]"
        )
    shifted = shifted.replace("KEYS[i + 2]", f"KEYS[i + {2 + _ADMISSION_KEY_SHIFT}]")
    shifted = shifted.replace("KEYS[i]", f"KEYS[i + {_ADMISSION_KEY_SHIFT}]")
    shifted = shifted.replace("ARGV[i]", f"ARGV[i + {_ADMISSION_ARG_SHIFT}]")
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
