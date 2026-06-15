# Skill Registry — mexa
Generated: 2026-04-30

## User Skills

| Skill | Trigger |
|-------|---------|
| branch-pr | Creating a PR, opening a PR, preparing changes for review |
| go-testing | Writing Go tests, teatest, Bubbletea TUI testing |
| issue-creation | Creating a GitHub issue, reporting a bug, requesting a feature |
| judgment-day | "judgment day", "juzgar", "doble review", adversarial review |
| skill-creator | Creating a new skill, documenting patterns for AI |
| skill-registry | "update skills", "skill registry", "actualizar skills" |

## Compact Rules

### branch-pr
- Always create the branch from an existing issue
- PR title: `type(scope): description` (conventional commits)
- Body must reference the issue: `Closes #N`
- Never push directly to main

### issue-creation
- Issue must exist before opening a PR
- Use labels: bug, feature, refactor, docs
- Include: problem statement, expected behavior, steps to reproduce (for bugs)

### judgment-day
- Launch two independent judge sub-agents simultaneously (blind to each other)
- Synthesize findings, apply fixes, re-judge up to 2 iterations
- Escalate if both judges still fail after 2 rounds

### skill-creator
- Follow Agent Skills spec format (frontmatter + SKILL.md)
- Include: When to Use, Rules, Examples
- Save to ~/.claude/skills/{name}/SKILL.md

## Project Conventions
- Python 3, Raspberry Pi 5
- Module per hardware concern (modulo_*.py)
- No linter, no formatter, no type checker configured
- Manual test scripts only (test_flujo.py, test_modulos.py)
