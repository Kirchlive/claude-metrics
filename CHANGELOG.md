# Changelog

All notable changes to Claude Metrics will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned for v2.1.0
- In-memory cache system (-98% cache I/O overhead)
- Buffered log writing (-98% write operations)
- Enhanced secret redaction (AWS, GitHub, Azure patterns)
- Architecture refactoring (Strategy Pattern for normalizers)
- Smart regex optimization (-85% pattern matching time)
- Performance improvement: ~84% faster overall

## [2.0.0] - 2025-11-06

### Added
- **Log Rotation & Compression**
  - Automatic rotation at 100MB threshold
  - Gzip compression for archived logs
  - Timestamp-based backup naming
- **Activity Duration Tracking**
  - Per-session activity timestamps
  - Duration calculation for tools and activities
  - `duration_ms` field in log entries
- **Token Consumption Tracking**
  - Input/output token metrics per tool use
  - Session-level token accumulation
  - `token_in` and `token_out` fields
- **Agent State Management**
  - Multi-agent session tracking
  - Subagent detection and logging
  - Agent stack management
- **Enhanced Schema**
  - `operator` field (main/agent/background)
  - `phase` field (pre/post/add/stop)
  - Normalized `output` structure
  - Background task tracking

### Changed
- Improved error handling in cache operations
- Optimized secret redaction patterns
- Enhanced output truncation with character count
- Better Bash command classification

### Fixed
- Silent failure in `write_log_line()` now logs to stderr
- Race conditions in cache file operations
- Clean text pattern handling for truncated strings

## [1.0.0] - 2025-10-15

### Added
- Initial release
- Basic event logging for Claude Code hooks
- Secret redaction (API keys, tokens, passwords)
- Text cleaning and normalization
- Tool output normalization (Bash, Read, Write, Edit, Grep, Glob)
- MCP tool support
- Session ID tracking (compact mode)
- Timestamp formatting (compact mode)
- Configurable field filtering

### Features
- JSONL log format
- Support for 9 hook events:
  - UserPromptSubmit
  - PreToolUse / PostToolUse
  - Stop / SubagentStop
  - SessionStart / SessionEnd
  - PreCompact
  - Notification
- Command classification (git, npm, docker, filesystem, network)
- Error type classification (permission, not_found, timeout, network, syntax)

---

## Version Numbering

- **Major (X.0.0)**: Breaking changes, incompatible API changes
- **Minor (x.Y.0)**: New features, backward-compatible
- **Patch (x.y.Z)**: Bug fixes, backward-compatible

## Links

- [Optimization Plan](docs/logger-optimization-plan.md)
- [Validated Roadmap](docs/logger-optimization-plan-v2-validated.md)
- [GitHub Repository](https://github.com/Kirchlive/claude-metrics)
