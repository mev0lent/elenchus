# Releases

Elenchus uses SemVer: `MAJOR.MINOR.PATCH`. Additive commands and modes bump MINOR;
bug fixes bump PATCH. Breaking command, hook, or persisted-state changes bump MAJOR
(while below 1.0, bump MINOR and describe the migration). Never change an existing tag.

The core is one release across Claude Code, Codex, and Vibe. Keep `version` identical in:

- `plugins/elenchus/.claude-plugin/plugin.json`
- `plugins/elenchus/.codex-plugin/plugin.json`
- `plugins/elenchus/plugin.json`

The optional UI has its own version in
`plugins/elenchus-ui/.claude-plugin/plugin.json`; do not bump it for core-only changes.
Core tags are `v<version>`; UI tags are `elenchus-ui-v<version>`.
The packaging tests reject mismatched core versions and invalid version numbers.

To release:

1. Update the affected manifests and add a dated entry to `CHANGELOG.md`. Include
   user-visible changes, migration steps, and checks that still need real hosts.
2. Run the checks below without piping away their exit codes. GitHub Actions runs the
   Python checks on pushes and pull requests. Claude's mods tests and manifest
   validation also run locally when its CLI is available.
3. Commit, push, wait for CI, and then create an annotated tag matching the manifest.
   Push that tag explicitly. Never force-push release history.

```sh
for t in test_gates test_vibe test_codex test_crossos test_launcher test_paper; do
  python3 plugins/elenchus/tests/$t.py || exit 1
done
python3 plugins/elenchus-ui/tests/test_palette.py || exit 1
python3 plugins/elenchus-ui/tests/test_theme.py || exit 1
claude plugin validate . || exit 1
claude plugin test plugins/elenchus-ui || exit 1

# Example, after the matching manifests and changelog are committed and CI passes:
git tag -a v0.10.0 -m 'Elenchus 0.10.0'
git push origin v0.10.0
```

Codex caches installed plugins. Refresh the installed copy after a release using
`codex plugin remove elenchus@elenchus` and `codex plugin add elenchus@elenchus`.
Restart open host sessions. Trust prompts and the always-on flag remain the user's
choices; a release must not enable them automatically.
