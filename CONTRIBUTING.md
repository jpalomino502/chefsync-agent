# Contributing to ChefSync Agent

Thanks for helping improve the agent.

## Before you start

- Open an issue for larger changes or behavior changes.
- Keep pull requests focused on one concern.
- Do not commit local environment files or build artifacts.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Code style

- Prefer small, focused functions.
- Keep platform-specific code isolated under `services/`.
- Update `README.md` whenever behavior, configuration, or endpoints change.

## Testing

- Use `scripts/test_print_integration.py` for manual print checks.
- If you add automated tests, place them under `scripts/` or a future `tests/` folder.

## Pull requests

- Describe what changed and why.
- Mention any printer models or OS-specific behavior affected.
- Note configuration changes in the README.