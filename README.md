# Claude Metrics

**Advanced event logging and metrics tracking system for Claude Code**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![GitHub](https://img.shields.io/badge/github-Kirchlive%2Fclaude--metrics-blue)](https://github.com/Kirchlive/claude-metrics)

## 🎯 Overview

Claude Metrics ist ein produktionsreifes Logging-System für [Claude Code](https://claude.ai/code), das detaillierte Event-Tracking, Token-Metriken und Performance-Analysen ermöglicht.

**Key Features:**
- 📊 **Comprehensive Event Tracking** - Alle Tool-Calls, Prompts & AI-Outputs
- 🔄 **Automatic Log Rotation** - Mit Gzip-Kompression bei 100MB
- 🛡️ **Secret Redaction** - Pattern-basiertes Filtern von API-Keys & Tokens
- ⚡ **Performance Metrics** - Duration-Tracking für Tools & Activities
- 🧩 **Agent State Management** - Multi-Agent Session-Tracking
- 📦 **Token Consumption** - Input/Output Token-Metriken pro Session

## 📋 Requirements

- Python 3.8+
- [uv](https://github.com/astral-sh/uv) (Package Manager)
- Claude Code CLI
- Dependency: `orjson >= 3.10.0`

## 🚀 Installation

### 1. Install via Hook Integration

```bash
# Clone repository
git clone https://github.com/Kirchlive/claude-metrics.git
cd claude-metrics

# Copy logger to Claude Code hooks directory
cp .claude/hooks/logger.py ~/.claude/hooks/

# Install dependency
uv pip install orjson
```

### 2. Configure Claude Code Settings

Add to `.claude/settings.local.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": "python ~/.claude/hooks/logger.py",
    "PreToolUse": "python ~/.claude/hooks/logger.py",
    "PostToolUse": "python ~/.claude/hooks/logger.py",
    "Stop": "python ~/.claude/hooks/logger.py",
    "SubagentStop": "python ~/.claude/hooks/logger.py",
    "SessionStart": "python ~/.claude/hooks/logger.py",
    "SessionEnd": "python ~/.claude/hooks/logger.py",
    "PreCompact": "python ~/.claude/hooks/logger.py",
    "Notification": "python ~/.claude/hooks/logger.py"
  }
}
```

## 📊 Log Output Format

Logs werden als **JSONL** (JSON Lines) gespeichert in `.claude/logs/claude-output.jsonl`:

```json
{
  "ts": "14:32:15",
  "sid": "a3f2b8c1",
  "operator": "main",
  "phase": "pre",
  "tool": "Bash",
  "input": {
    "description": "List files in current directory",
    "command": "ls -la"
  }
}
```

### Schema Fields

| Field | Description | Example |
|-------|-------------|---------|
| `ts` | Timestamp (compact: HH:MM:SS) | `"14:32:15"` |
| `sid` | Session ID (8 chars) | `"a3f2b8c1"` |
| `operator` | Actor type (main/agent/background) | `"main"` |
| `phase` | Event phase (pre/post/add/stop) | `"pre"` |
| `tool` | Tool name | `"Bash"`, `"Read"` |
| `input` | Tool input (truncated) | `{"command": "..."}` |
| `output` | Normalized output | `{"status": "success", "data": "..."}` |
| `duration_ms` | Execution time | `1250` |
| `token_in` | Input tokens | `523` |
| `token_out` | Output tokens | `187` |

## 🔧 Configuration

### Constants (logger.py)

```python
LOG_FILE = ".claude/logs/claude-output.jsonl"
MAX_LOG_SIZE_MB = 100              # Rotation threshold
REDACT_SECRETS = True              # Enable secret filtering
CLEAN_OUTPUT_TEXT = True           # Clean escaped chars
TS_CONFIG = "compact"              # Timestamp format
SID_CONFIG = "compact"             # Session ID format (8 chars)
MAX_LENGTH = 250                   # Truncation limit
```

### Secret Patterns

Der Logger erkennt und redacted automatisch:
- API Keys (`api_key`, `apikey`)
- Bearer Tokens (`Authorization: Bearer ...`)
- OpenAI Keys (`sk-...`)
- Passwords (`password=...`)
- Generic tokens (`token=...`)

## 📈 Performance

**v2.0.0 Benchmarks** (10,000 Events):
- Latenz: `~0.7ms` pro Event
- Disk I/O: `~2.8ms` (Cache-Operations)
- Log Rotation: `<100ms` (bei 100MB)

**Geplante Optimierungen** (v2.1.0):
- `-84%` Latenz (3.96ms → 0.62ms)
- In-Memory Cache System
- Buffered Log Writing
- Enhanced Secret Patterns (AWS, GitHub, Azure)

Siehe [Logger Optimization Plan](docs/logger-optimization-plan.md)

## 🗂️ Project Structure

```
claude-metrics/
├── .claude/
│   ├── hooks/
│   │   └── logger.py           # Main logger hook
│   └── logs/
│       ├── claude-output.jsonl  # Event logs
│       ├── tool_timestamps.json # Duration cache
│       ├── agent_state.json     # Agent stack
│       └── session_tokens.json  # Token metrics
├── docs/
│   ├── logger-optimization-plan.md
│   └── ...
├── tests/
│   └── phase1_integration_test_results.md
├── README.md
├── CHANGELOG.md
└── LICENSE
```

## 🛠️ Development Roadmap

### ✅ v2.0.0 (Current)
- [x] Log rotation + gzip compression
- [x] Activity duration tracking
- [x] Version tracking
- [x] Schema fields extension

### 🔄 v2.1.0 (Planned)
- [ ] In-memory cache system
- [ ] Buffered log writing
- [ ] Enhanced secret redaction (AWS, GitHub, Azure)
- [ ] Architecture refactoring (Strategy Pattern)
- [ ] Performance optimization (~84% faster)

Siehe [CHANGELOG.md](CHANGELOG.md) für Details.

## 📝 Usage Examples

### Analyze Token Consumption

```bash
# Total tokens per session
jq -s 'group_by(.sid) | map({sid: .[0].sid, total_in: map(.token_in // 0) | add, total_out: map(.token_out // 0) | add})' .claude/logs/claude-output.jsonl
```

### Track Tool Performance

```bash
# Average duration by tool
jq -s 'group_by(.tool) | map({tool: .[0].tool, avg_ms: (map(.duration_ms // 0) | add / length)})' .claude/logs/claude-output.jsonl
```

### Extract Agent Activity

```bash
# Filter subagent events
jq 'select(.operator != "main")' .claude/logs/claude-output.jsonl
```

## 🤝 Contributing

Contributions welcome! Bitte beachten:
1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'feat: Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

## 📄 License

MIT License - siehe [LICENSE](LICENSE)

## 🙏 Acknowledgments

- Built for [Claude Code](https://claude.ai/code) by Anthropic
- Powered by [orjson](https://github.com/ijl/orjson) for fast JSON serialization
- Package management via [uv](https://github.com/astral-sh/uv)

## 📬 Contact

Project Link: [https://github.com/Kirchlive/claude-metrics](https://github.com/Kirchlive/claude-metrics)

---

⭐ **Star this repo** if you find it useful!
