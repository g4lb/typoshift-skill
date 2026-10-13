# Examples

All outputs below are real. They were produced with the default configuration (`typoshift 0.1.0`).

## CLI

```text
$ typoshift fix "פךקשדק גקהקךםפ איק מקסא כקשאורק"
please develop the next feature

$ typoshift fix "please implement the login פשעק"
please implement the login page

$ typoshift fix "ghbdtn rfr ltkf&"
привет как дела?

$ typoshift fix "Руддщ цщкдв"
Hello world

$ typoshift fix "Please update src/components/Header.tsx"
Please update src/components/Header.tsx

$ typoshift detect "hello world"; echo "exit $?"
no keyboard-layout mistake detected
exit 1

$ typoshift convert --from he --to en-US "פךקשדק"
please
```

## Python

See [`api_usage.py`](api_usage.py) and [`hook_payload.json`](hook_payload.json). To exercise the
Claude Code hook by hand:

```bash
typoshift hook claude-code < examples/hook_payload.json
```
