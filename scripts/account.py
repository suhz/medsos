"""CLI: list accounts. (No add here — use the HTTP /accounts/authorize or the
medsos_add_account tool; the CLI doesn't have a browser for OAuth.)"""
import json
import medsos.ops as ops


def main() -> int:
    rows = ops.find_accounts()
    print(json.dumps(rows, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())