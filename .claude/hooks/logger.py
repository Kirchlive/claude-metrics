#!/usr/bin/env -S uv run --quiet --script
# dependencies = ["orjson>=3.10.0"]

import sys
import os
import time
import gzip
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import re

try:
    import orjson
except ImportError:
    print("Error: orjson not available. Install with: uv pip install orjson", file=sys.stderr)
    sys.exit(0)

# ============================================================================
# CONFIGURATION
# ============================================================================

LOG_FILE = ".claude/logs/claude-output.jsonl"
LOG_PATH = Path(LOG_FILE)
TIMESTAMP_CACHE = ".claude/logs/tool_timestamps.json"
TIMESTAMP_CACHE_PATH = Path(TIMESTAMP_CACHE)
AGENT_STATE_CACHE = LOG_PATH.parent / "agent_state.json"
TOKEN_CACHE = LOG_PATH.parent / "session_tokens.json"
MAX_LOG_SIZE_MB = 100
MAX_CACHE_ENTRIES = 1000
REDACT_SECRETS = True
CLEAN_OUTPUT_TEXT = True
TS_CONFIG = "compact"
SID_CONFIG = "compact"
MAX_LENGTH = 250
ALWAYS_INCLUDE_FIELDS = {"token_in", "token_out"}

FIELD_CONFIG = {
    "ts": True,
    "sid": True,
    "operator_top": False,
    "operator": True,
    "event": False,
    "phase": True,
    "tool": True,
    "input": True,
    "output": True,
    "bg_task_id": True,
    "role": False,
    "prompt": True,
    "mode": True,
    "content": True,
    "custom_instructions": True,
    "level": True,
    "message": True,
    "cwd": True,
    "permission_mode": True,
    "reason": True,
    "meta": True,
    "duration_ms": True,
    "source": True,
    "token_in": True,
    "token_out": True,
    "transcript_path": True,
    "trigger": True,
    "analysis_type": True,
    "author": True,
    "category": True,
}

COMPILED_CLEAN_PATTERNS = [
    (re.compile(r'\\n'), ' '),
    (re.compile(r'\\t'), ' '),
    (re.compile(r'\\r'), ' '),
    (re.compile(r',\s*\\"'), ',"'),
    (re.compile(r':\s*\\"'), ':"'),
    (re.compile(r'\\"'), '"'),
    (re.compile(r'\{\s+\"'), '{"'),
    (re.compile(r'\"\s+\}'), '"}'),
    (re.compile(r'\s{2,}'), ' '),
    (re.compile(r'(.)\1{3,}'), r'\1')
]

SECRET_PATTERNS = [
    (re.compile(r'["\']?api[_-]?key["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
     r'api_key="[REDACTED]"'),
    (re.compile(r'["\']?token["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.]{20,})["\']?', re.IGNORECASE),
     r'token="[REDACTED]"'),
    (re.compile(r'["\']?password["\']?\s*[:=]\s*["\']?([^\s"\']{8,})["\']?', re.IGNORECASE),
     r'password="[REDACTED]"'),
    (re.compile(r'Bearer\s+([a-zA-Z0-9_\-\.]{20,})', re.IGNORECASE),
     r'Bearer [REDACTED]'),
    (re.compile(r'sk-[a-zA-Z0-9]{20,}', re.IGNORECASE),
     r'sk-[REDACTED]'),
]

COMMAND_PREFIXES = {
    "git": ("git ", "gh "),
    "package_manager": ("npm ", "yarn ", "pnpm ", "bun ", "pip ", "poetry ", "cargo "),
    "container": ("docker ", "docker-compose ", "kubectl ", "podman "),
    "filesystem": ("ls ", "cd ", "mkdir ", "rm ", "cp ", "mv ", "cat ", "touch ", "chmod ", "chown "),
    "network": ("curl ", "wget ", "ping ", "ssh ", "scp ", "nc ", "telnet "),
    "runtime": ("python ", "node ", "ruby ", "java ", "go run ", "rust "),
    "build": ("make ", "cmake ", "gcc ", "g++ ", "clang "),
}

ERROR_KEYWORDS = {
    "permission": ("permission denied", "eacces"),
    "not_found": ("not found", "enoent", "does not exist"),
    "timeout": ("timeout", "timed out"),
    "network": ("connection", "network", "unreachable"),
    "syntax": ("syntax", "parse", "invalid syntax"),
}

# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def _validate_config() -> None:
    """Validate configuration values at startup"""
    assert MAX_LENGTH > 0, "MAX_LENGTH must be positive"
    assert MAX_LOG_SIZE_MB > 0, "MAX_LOG_SIZE_MB must be positive"
    assert MAX_CACHE_ENTRIES > 0, "MAX_CACHE_ENTRIES must be positive"
    assert TS_CONFIG in ("compact", "full"), f"Invalid TS_CONFIG: {TS_CONFIG}"
    assert SID_CONFIG in ("compact", "full"), f"Invalid SID_CONFIG: {SID_CONFIG}"

# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

def _load_cache(cache_file: Path) -> Dict:
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file, "rb") as f:
            return orjson.loads(f.read())
    except (OSError, orjson.JSONDecodeError):
        return {}

def _save_cache(cache_file: Path, data: Dict) -> None:
    try:
        _ensure_log_dir()
        with open(cache_file, "wb") as f:
            f.write(orjson.dumps(data))
    except OSError:
        pass


def _cleanup_cache_if_needed(cache_file: Path, max_entries: int = MAX_CACHE_ENTRIES) -> None:
    """Remove oldest cache entries if exceeding threshold"""
    try:
        cache = _load_cache(cache_file)
        if len(cache) <= max_entries:
            return

        # For timestamp cache: keep entries with most recent timestamps
        # For other caches: keep most recently accessed entries
        if cache_file == TIMESTAMP_CACHE_PATH:
            # Extract timestamp entries (format: "session:tool" or "session:last_activity")
            sorted_items = sorted(
                cache.items(),
                key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0,
                reverse=True
            )
        else:
            # For agent_state and token cache, keep based on dict structure
            sorted_items = list(cache.items())

        # Keep only the most recent entries
        trimmed_cache = dict(sorted_items[:max_entries])
        _save_cache(cache_file, trimmed_cache)
    except (OSError, TypeError, ValueError):
        pass

# ============================================================================
# LOG ROTATION
# ============================================================================

def gzip_file(filepath: Path) -> bool:
    try:
        gz_filepath = Path(str(filepath) + ".gz")
        
        with open(filepath, 'rb') as f_in:
            with gzip.open(gz_filepath, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        try:
            filepath.unlink()
        except OSError:
            pass
        
        return True
    except OSError as e:
        print(f"Warning: Failed to gzip {filepath}: {e}", file=sys.stderr)
        return False


def rotate_logs_if_needed(log_filepath: Path, max_size_mb: int = 100) -> bool:
    try:
        if not log_filepath.exists():
            return False
        
        file_size_bytes = log_filepath.stat().st_size
        max_size_bytes = max_size_mb * 1024 * 1024
        
        if file_size_bytes < max_size_bytes:
            return False
        
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        backup_name = f"{log_filepath.stem}.{timestamp}{log_filepath.suffix}"
        backup_path = log_filepath.parent / backup_name
        
        shutil.move(str(log_filepath), str(backup_path))
        
        gzip_file(backup_path)


        _ensure_log_dir()
        log_filepath.touch()
        
        size_mb = file_size_bytes / (1024 * 1024)
        print(f"Log rotated: {log_filepath.name} ({size_mb:.2f}MB) → {backup_name}.gz", 
              file=sys.stderr)
        
        return True

    except OSError as e:
        print(f"Warning: Log rotation failed for {log_filepath}: {e}", file=sys.stderr)
        return False

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _ensure_log_dir() -> None:
    """Ensure log directory exists (internal helper)"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def save_tool_start_time(session_id: str, tool_name: str, timestamp: str) -> None:
    cache = _load_cache(TIMESTAMP_CACHE_PATH)
    cache[f"{session_id}:{tool_name}"] = time.time()
    _cleanup_cache_if_needed(TIMESTAMP_CACHE_PATH)
    _save_cache(TIMESTAMP_CACHE_PATH, cache)


def get_tool_duration_ms(session_id: str, tool_name: str, end_time: str) -> Optional[int]:
    cache = _load_cache(TIMESTAMP_CACHE_PATH)
    cache_key = f"{session_id}:{tool_name}"

    start_time_epoch = cache.get(cache_key)

    end_time_epoch = time.time()

    if not start_time_epoch:
        cache[cache_key] = end_time_epoch
        _save_cache(TIMESTAMP_CACHE_PATH, cache)
        return None

    try:
        duration = int((end_time_epoch - start_time_epoch) * 1000)

        del cache[cache_key]
        _save_cache(TIMESTAMP_CACHE_PATH, cache)

        return duration
    except (ValueError, KeyError, TypeError):
        return None


def save_agent_state(session_id: str, subagent_name: str) -> None:
    cache = _load_cache(AGENT_STATE_CACHE)
    cache.setdefault(session_id, []).append(subagent_name)
    _cleanup_cache_if_needed(AGENT_STATE_CACHE)
    _save_cache(AGENT_STATE_CACHE, cache)


def get_current_agent(session_id: str) -> Optional[str]:
    cache = _load_cache(AGENT_STATE_CACHE)
    agents = cache.get(session_id, [])
    return agents[-1] if agents else None


def clear_agent_state(session_id: str) -> None:
    cache = _load_cache(AGENT_STATE_CACHE)
    if session_id in cache and cache[session_id]:
        cache[session_id].pop()
        if not cache[session_id]:
            del cache[session_id]
        _save_cache(AGENT_STATE_CACHE, cache)


def update_session_tokens(session_id: str, input_tokens: int, output_tokens: int) -> Optional[Dict[str, int]]:
    cache = _load_cache(TOKEN_CACHE)

    if session_id not in cache:
        cache[session_id] = {"input": 0, "output": 0, "total": 0}

    cache[session_id]["input"] += input_tokens
    cache[session_id]["output"] += output_tokens
    cache[session_id]["total"] = cache[session_id]["input"] + cache[session_id]["output"]

    _cleanup_cache_if_needed(TOKEN_CACHE)
    _save_cache(TOKEN_CACHE, cache)
    return cache[session_id].copy()


def save_activity_timestamp(session_id: str) -> None:
    cache = _load_cache(TIMESTAMP_CACHE_PATH)
    cache[f"{session_id}:last_activity"] = time.time()
    _cleanup_cache_if_needed(TIMESTAMP_CACHE_PATH)
    _save_cache(TIMESTAMP_CACHE_PATH, cache)


def get_activity_duration_ms(session_id: str) -> Optional[int]:
    cache = _load_cache(TIMESTAMP_CACHE_PATH)
    cache_key = f"{session_id}:last_activity"
    
    start_time_epoch = cache.get(cache_key)
    if not start_time_epoch:
        return None
    
    try:
        end_time_epoch = time.time()
        duration = int((end_time_epoch - start_time_epoch) * 1000)
        return duration
    except (ValueError, TypeError):
        return None


def _ensure_text(value: Any) -> str:
    """Convert any value to string representation"""
    if isinstance(value, (list, dict)):
        try:
            return orjson.dumps(value).decode("utf-8")
        except Exception:
            pass  # Fallthrough to str()
    return str(value)


def truncate(value: Any) -> Any:
    if not value:
        return value

    text = _ensure_text(value)
    text = redact_secrets(text)

    if len(text) > MAX_LENGTH:
        return f'{text[:MAX_LENGTH]}...{{characters:{len(text)}}}'

    return text


def _extract_content(tool_response: Dict, keys: Tuple[str, ...]) -> Optional[Any]:
    for key in keys:
        if key in tool_response:
            return tool_response[key]
    return None


def _extract_mcp_text(data: Any) -> str:
    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict) and "text" in data[0]:
            return data[0]["text"]
    if isinstance(data, dict) and "text" in data:
        return data["text"]
    return str(data)


def normalize_tool_output(tool_name: str, tool_response: Dict[str, Any],
                         tool_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = {"status": "success", "data": None, "error": None, "meta": {}}

    if tool_name == "Bash":
        exit_code = tool_response.get("exit_code", 0)
        normalized["status"] = "success" if exit_code == 0 else "error"
        normalized["data"] = truncate(tool_response.get("stdout", ""))
        if exit_code != 0:
            normalized["error"] = truncate(tool_response.get("stderr", ""))
        normalized["meta"]["exit_code"] = exit_code

        if tool_input and (command := tool_input.get("command")):
            normalized["meta"]["commandType"] = classify_command(command)

    elif tool_name in ["Read", "Write", "Edit", "Glob", "Grep"]:
        normalized["status"] = "success" if tool_response.get("success", True) else "error"

        content_data = None
        if file_data := tool_response.get("file"):
            content_data = file_data.get("content") if isinstance(file_data, dict) else None
        elif tool_name == "Edit" and "originalFile" in tool_response:
            old_str, new_str = tool_response.get("oldString", ""), tool_response.get("newString", "")
            if old_str and new_str:
                content_data = (f"Changed: '{old_str}' → '{new_str}'" if len(old_str) <= 50 and len(new_str) <= 50
                              else f"Changed: '{old_str[:30]}...' → '{new_str[:30]}...'")
                normalized["meta"]["charsChanged"] = len(new_str) - len(old_str)
        else:
            content_data = _extract_content(tool_response, ("content", "result", "lines", "filenames", "data"))

            if tool_name == "Grep" and "lines" in tool_response:
                normalized["meta"]["matchCount"] = len(tool_response["lines"])
            elif tool_name == "Glob" and (filenames := tool_response.get("filenames")):
                normalized["meta"]["matchCount"] = len(filenames)

        if content_data is not None:
            normalized["data"] = truncate(content_data if not isinstance(content_data, list)
                                        else "\n".join(content_data))

    elif tool_name == "WebSearch":
        results = tool_response.get("results", [])
        summary = results[1] if isinstance(results, list) and len(results) > 1 else None
        normalized["data"] = truncate(summary) if summary else f"Search for: {tool_response.get('query', '')}"
        normalized["meta"]["query"] = tool_response.get("query", "")

        if duration := tool_response.get("durationSeconds"):
            normalized["meta"]["durationSeconds"] = duration

    elif tool_name == "Task":
        data = tool_response.get("data", tool_response.get("output"))

        if isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict) and "text" in data[0]:
                normalized["data"] = truncate(data[0]["text"])
            else:
                normalized["data"] = truncate(str(data))
        else:
            normalized["data"] = truncate(data)

        if subagent := tool_response.get("subagent_type"):
            normalized["meta"]["subagent"] = subagent
        if duration := tool_response.get("durationMs"):
            normalized["meta"]["duration"] = duration

    elif tool_name.startswith("mcp__"):
        tool_parts = tool_name.split("__")
        if len(tool_parts) >= 3:
            normalized["meta"].update({"mcpServer": tool_parts[1], "mcpAction": "__".join(tool_parts[2:])})

        if isinstance(tool_response, dict):
            result = tool_response.get("result")
            if isinstance(result, str):
                try:
                    normalized["data"] = truncate(orjson.loads(result))
                except:
                    normalized["data"] = truncate(result)
            elif isinstance(result, list):
                normalized["data"] = truncate(_extract_mcp_text(result))
            else:
                normalized["data"] = truncate(result)
        elif isinstance(tool_response, list):
            normalized["data"] = truncate(_extract_mcp_text(tool_response))
        elif isinstance(tool_response, str):
            normalized["data"] = truncate(tool_response)

    else:
        normalized["status"] = ("success" if tool_response.get("success",
                              tool_response.get("exit_code", 0) == 0) else "error")

        normalized["data"] = truncate(_extract_content(tool_response,
                                      ("output", "result", "content", "data", "response")))
        normalized["error"] = truncate(_extract_content(tool_response,
                                      ("error", "stderr", "error_message")))

    if normalized["error"]:
        normalized.setdefault("meta", {})["errorType"] = classify_error(normalized["error"])

    return {k: v for k, v in normalized.items() if v or k == "data"}


def redact_secrets(text: str) -> str:
    if not REDACT_SECRETS or not text:
        return text

    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _apply_clean_patterns(text: str) -> str:
    for pattern, replacement in COMPILED_CLEAN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def clean_text(text: str) -> str:
    if not text or not CLEAN_OUTPUT_TEXT:
        return text

    if '...{characters:' in text:
        parts = text.split('...{characters:', 1)
        cleaned = _apply_clean_patterns(parts[0])
        return f"{cleaned}...{{characters:{parts[1]}"
    
    return _apply_clean_patterns(text)


def safe_get(data: Dict, *keys: str, default: Any = None) -> Any:
    result = data
    for key in keys:
        if not isinstance(result, dict):
            return default
        result = result.get(key, default)
    return result


def classify_error(error_msg: str) -> str:
    if not error_msg:
        return "unknown"

    error_lower = error_msg.lower()
    for error_type, keywords in ERROR_KEYWORDS.items():
        if any(kw in error_lower for kw in keywords):
            return error_type
    return "unknown"


def classify_command(command: str) -> str:
    if not command:
        return "system"

    cmd_lower = command.lower().strip()
    for cmd_type, prefixes in COMMAND_PREFIXES.items():
        if cmd_lower.startswith(prefixes):
            return cmd_type
    return "system"


def filter_fields(log_entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v for k, v in log_entry.items()
        if k in ALWAYS_INCLUDE_FIELDS or FIELD_CONFIG.get(k, True)
    }


def format_timestamp() -> str:
    dt = datetime.now()
    if TS_CONFIG == "compact":
        return dt.strftime("%H:%M:%S")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4]


def format_session_id(session_id: str) -> str:
    if not session_id:
        return ""

    if SID_CONFIG == "compact":
        return session_id[:8]
    else:
        return session_id


def determine_operator(event_name: str, hook_input: Dict[str, Any], session_id: str, level: str = "top") -> str:
    """
    Determine operator at given level.

    Args:
        event_name: Name of the hook event
        hook_input: Hook input data
        session_id: Current session ID
        level: "top" for high-level actor (user/main/subagent/background)
               "detailed" for detailed agent type (user/main/agent-name/background)

    Returns:
        Operator string based on level
    """
    if event_name == "UserPromptSubmit":
        return "user"

    if hook_input.get("background_task_id"):
        return "background"

    if event_name == "PreToolUse":
        tool_input = hook_input.get("tool_input", {})
        if tool_input.get("run_in_background"):
            return "background"

        if hook_input.get("tool_name") == "Task":
            if level == "detailed" and (subagent := tool_input.get("subagent_type")):
                save_agent_state(session_id, subagent)
            return "main"

    elif event_name == "SubagentStop" and level == "detailed":
        current = get_current_agent(session_id)
        clear_agent_state(session_id)
        return current or "agent"

    # Determine based on level
    current_agent = get_current_agent(session_id)
    if level == "top":
        return "subagent" if current_agent else "main"
    else:  # detailed
        return current_agent or "main"


def extract_event_data(hook_input: Dict[str, Any]) -> Dict[str, Any]:
    event_name = hook_input.get("hook_event_name", "unknown")
    session_id_original = hook_input.get("session_id", "")
    timestamp = format_timestamp()

    base = {
        "ts": timestamp,
        "sid": format_session_id(session_id_original),
        "operator_top": determine_operator(event_name, hook_input, session_id_original, level="top"),
        "operator": determine_operator(event_name, hook_input, session_id_original, level="detailed"),
        "event": event_name,
    }

    if event_name == "UserPromptSubmit":
        save_activity_timestamp(session_id_original)
        base.update({
            "phase": "add",
            "tool": "prompt",
            "input": {
                "content": truncate(safe_get(hook_input, "prompt", default="")),
                "mode": truncate(safe_get(hook_input, "mode", default="default"))
            }
        })

    elif event_name == "PreToolUse":
        tool_name = safe_get(hook_input, "tool_name", default="Unknown")
        tool_input = safe_get(hook_input, "tool_input", default={})

        save_tool_start_time(session_id_original, tool_name, timestamp)

        extracted_input = {k: truncate(v) for k, v in tool_input.items()} if isinstance(tool_input, dict) else {}

        if tool_name == "Bash" and isinstance(extracted_input, dict):
            reordered = {}
            if "description" in extracted_input:
                reordered["description"] = extracted_input["description"]
            if "command" in extracted_input:
                reordered["command"] = extracted_input["command"]
            for k, v in extracted_input.items():
                if k not in ("description", "command"):
                    reordered[k] = v
            extracted_input = reordered

        if extracted_input or tool_input:
            base.update({"phase": "pre", "tool": tool_name, "input": extracted_input})
        else:
            base.update({"phase": "pre", "tool": tool_name})

    elif event_name == "PostToolUse":
        tool_name = safe_get(hook_input, "tool_name", default="Unknown")
        tool_response = safe_get(hook_input, "tool_response", default={})
        tool_input = safe_get(hook_input, "tool_input", default={})

        duration_ms = get_tool_duration_ms(session_id_original, tool_name, timestamp)
        output = normalize_tool_output(tool_name, tool_response, tool_input)

        base.update({"phase": "post", "tool": tool_name, "output": output})

        if duration_ms is not None:
            base["duration_ms"] = duration_ms

        if bg_task_id := safe_get(hook_input, "background_task_id"):
            base["bg_task_id"] = bg_task_id

        if usage := safe_get(tool_response, "usage"):
            if (inp := usage.get("input_tokens")) is not None:
                base["token_in"] = inp
            if (out := usage.get("output_tokens")) is not None:
                base["token_out"] = out

            if inp is not None and out is not None:
                update_session_tokens(session_id_original, inp, out)
        
        if not hook_input.get("background_task_id"):
            save_activity_timestamp(session_id_original)

    elif event_name in ["Stop", "SubagentStop"]:
        if hook_input.get("stop_hook_active"):
            base.update({
                "phase": "stop",
                "tool": "hook",
                "output": {"status": "skipped", "data": "stop_hook_active"}
            })
            return base

        content = ""
        transcript_path = safe_get(hook_input, "transcript_path", default="")
        
        if transcript_path and os.path.exists(transcript_path):
            try:
                with open(transcript_path, 'r') as f:
                    lines = f.readlines()
                
                for line in reversed(lines[-20:]):
                    try:
                        entry = orjson.loads(line)
                        if entry.get("type") == "assistant":
                            msg_content = entry.get("message", {}).get("content", [])
                            for block in msg_content:
                                if block.get("type") == "text":
                                    content = block.get("text", "")
                                    break
                            if content:
                                break
                    except:
                        continue
            except Exception:
                pass
        
        duration_ms = get_activity_duration_ms(session_id_original)
        
        base.update({
            "phase": "stop",
            "tool": "Message",
            "output": {
                "status": "success",
                "data": truncate(content),
                "meta": {}
            }
        })
        
        if duration_ms is not None:
            base["duration_ms"] = duration_ms
        
        save_activity_timestamp(session_id_original)

    elif event_name == "Notification":
        base.update({
            "phase": "pre",
            "level": safe_get(hook_input, "level", default="info"),
            "message": truncate(safe_get(hook_input, "message", default="")),
        })

    elif event_name == "SessionStart":
        base.update({
            "phase": "start",
            "cwd": truncate(safe_get(hook_input, "cwd", default="")),
            "source": truncate(safe_get(hook_input, "source", default="")),
            "transcript_path": truncate(safe_get(hook_input, "transcript_path", default="")),
            "permission_mode": truncate(safe_get(hook_input, "permission_mode", default=""))
        })

    elif event_name == "SessionEnd":
        base.update({
            "phase": "end",
            "reason": truncate(safe_get(hook_input, "reason", default="")),
            "transcript_path": truncate(safe_get(hook_input, "transcript_path", default="")),
            "cwd": truncate(safe_get(hook_input, "cwd", default=""))
        })

    elif event_name == "PreCompact":
        base.update({
            "phase": "compact",
            "trigger": truncate(safe_get(hook_input, "trigger", default="")),
            "custom_instructions": truncate(safe_get(hook_input, "custom_instructions", default=""))
        })

    elif event_name == "AIOutput":
        base.update({
            "phase": "analysis",
            "content": truncate(safe_get(hook_input, "content", default="")),
            "analysis_type": safe_get(hook_input, "analysis_type", default="general"),
            "author": "claude-ai",
            "category": safe_get(hook_input, "category", default="undefined"),
        })

    return base

# ============================================================================
# LOGGING
# ============================================================================

def create_error_post_event(session_id: str, tool_name: str, error: Exception, timestamp: str) -> Dict[str, Any]:
    return {
        "ts": timestamp,
        "sid": format_session_id(session_id),
        "operator_top": "main",
        "operator": "main",
        "event": "PostToolUse",
        "phase": "post",
        "tool": tool_name,
        "output": {
            "status": "error",
            "data": None,
            "error": str(error),
            "meta": {"errorType": type(error).__name__, "errorClass": "RuntimeError"}
        },
        "duration_ms": get_tool_duration_ms(session_id, tool_name, timestamp) or 0
    }


def write_log_line(log_entry: Dict[str, Any]) -> None:
    try:
        _ensure_log_dir()

        rotate_logs_if_needed(LOG_PATH, MAX_LOG_SIZE_MB)

        json_bytes = orjson.dumps(log_entry)

        json_str = json_bytes.decode('utf-8')
        json_cleaned = clean_text(json_str)
        json_bytes_final = json_cleaned.encode('utf-8')

        with open(LOG_PATH, "ab") as f:
            f.write(json_bytes_final)
            f.write(b"\n")
            f.flush()
    except Exception:
        pass


def log_ai_output(session_id: str, content: str, analysis_type: str = "general", category: str = "analysis") -> None:
    """
    Public API: Log custom AI output or analysis to the event log.

    This function can be called from external tools or scripts to log
    custom AI-generated content or analysis results.

    Args:
        session_id: Session identifier
        content: AI output content to log
        analysis_type: Type of analysis (default: "general")
        category: Category of the output (default: "analysis")

    Example:
        log_ai_output("session123", "Code review complete", "review", "code-quality")
    """
    try:
        hook_input = {
            "hook_event_name": "AIOutput",
            "session_id": session_id,
            "content": content,
            "analysis_type": analysis_type,
            "category": category
        }

        event_data = extract_event_data(hook_input)
        filtered_data = filter_fields(event_data)
        write_log_line(filtered_data)
    except Exception:
        pass


def log_error(error_msg: str) -> None:
    if not error_msg:
        return
    
    try:
        entry = {
            "ts": format_timestamp(),
            "sid": "",
            "operator_top": "system",
            "operator": "system",
            "event": "LoggerError",
            "phase": "error",
            "tool": "logger",
            "message": truncate(error_msg),
            "output": {
                "status": "error",
                "data": None,
                "error": truncate(error_msg),
                "meta": {"errorType": "logger"}
            }
        }
        write_log_line(filter_fields(entry))
    except Exception:
        print(f"[logger] {error_msg}", file=sys.stderr)

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main() -> None:
    # Validate configuration at startup
    try:
        _validate_config()
    except AssertionError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    is_test_mode = os.getenv("HOOK_TEST") == "1"
    test_result = {"ok": True, "result": None, "logs": []}

    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            if is_test_mode:
                print(orjson.dumps({"ok": True, "result": "empty_input", "logs": []}).decode('utf-8'))
            sys.exit(0)

        try:
            hook_input = orjson.loads(raw_input)
        except orjson.JSONDecodeError as e:
            error_msg = f"JSON parse error: {e}"
            if is_test_mode:
                print(orjson.dumps({"ok": False, "result": None, "logs": [error_msg]}).decode('utf-8'))
            sys.exit(0)

        event_name = hook_input.get("hook_event_name", "test_event")
        session_id = hook_input.get("session_id", "test_session")

        try:
            event_data = extract_event_data(hook_input)
            filtered_data = filter_fields(event_data)

            if not is_test_mode:
                write_log_line(filtered_data)

            test_result["result"] = {
                "event": event_name,
                "processed": True,
                "data": filtered_data if is_test_mode else {"status": "logged"}
            }

        except Exception as e:
            test_result["ok"] = False
            test_result["logs"].append(f"Hook execution error: {e}")
            if not is_test_mode:
                log_error(f"Hook execution error: {e}")

            if event_name == "PostToolUse":
                error_event = create_error_post_event(
                    session_id, hook_input.get("tool_name", "Unknown"), e, format_timestamp()
                )
                if not is_test_mode:
                    write_log_line(filter_fields(error_event))

    except Exception as e:
        test_result["ok"] = False
        test_result["logs"].append(f"Critical hook error: {e}")
        if not is_test_mode:
            log_error(f"Critical hook error: {e}")

    finally:
        if is_test_mode:
            print(orjson.dumps(test_result).decode('utf-8'))
        sys.exit(0)


if __name__ == "__main__":
    main()
