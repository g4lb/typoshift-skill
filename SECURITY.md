# Security policy

## Reporting a vulnerability

Report vulnerabilities privately: use GitHub's "Report a vulnerability" (Security Advisories) on
the repository, or e-mail galevgi@gmail.com. Do not open public issues for security problems.
Expect an acknowledgement within 7 days.

## Security model

- **Offline.** At runtime TypoShift performs no network I/O. Prompts are never sent anywhere,
  logged, or stored. Only the developer tools in `tools/` download data, from pinned upstream
  commits.
- **No code execution from input.** Text is only analyzed and rewritten. The engine never
  evaluates or executes prompt content.
- **Claude Code hook.**
  - The hook reads the prompt JSON on stdin and writes context JSON on stdout.
  - It always exits 0 and never blocks a prompt, so a crash cannot lock you out of Claude Code.
  - It cannot replace your prompt. It only adds a reconstruction next to it.
  - Uncertain reconstructions are marked "do not act without asking".
  - Reconstructions that contain destructive verbs require explicit confirmation.
- **Installer.**
  - It changes settings only when you run `typoshift install` or `typoshift uninstall`.
  - It refuses to modify invalid JSON.
  - It backs up `settings.json` before writing, and writes atomically.
  - It touches only entries it created, identified by the `typoshift hook claude-code` command and
    the `.typoshift-managed` marker.
- **Secrets.** API-key formats, high-entropy strings, URLs and e-mail addresses are protected from
  rewriting. Reconstructions are included in the agent's context, and that context holds only text
  you already typed.

## Supported versions

Security fixes are released for the latest minor version.
