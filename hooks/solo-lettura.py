#!/usr/bin/env python3
"""Hold the site-auditor to reading, and let the harness be the one that says no.

The auditor's description says it changes nothing, which is why people point it
at a client's site in production. That sentence lived in a prompt, and the agent
holds Bash, which stages, commits, pushes and deploys. A model that misreads its
instructions, or a page carrying an instruction of its own that gets fetched
during an audit, could do every one of the things the description rules out.

So the rule lives here instead of in prose. This runs before the auditor's shell
calls. Outside the auditor it stays out of the way and prints nothing, because
publishing is the other half of this plugin and publishing needs git to write.

The list below is an allowlist on purpose. A list of forbidden commands is a
list of the ones somebody thought of, and `sh -c 'git push'` is never on it.

Input is the PreToolUse payload on stdin. Output is a deny decision on stdout,
or nothing at all when the command may run.
"""

from __future__ import annotations

import json
import shlex
import sys

# The agent this covers, by the name in its frontmatter. Claude Code puts that
# name in `agent_type` for every tool call made inside a subagent, and leaves
# the field out for the main session.
#
# Installed as a plugin, the name arrives with the plugin in front of it:
# `varo:site-auditor`. Loaded from a folder during development it can arrive
# bare. Both count, which is why the comparison below takes the part after the
# colon. This was not guesswork: the bare name alone let a write straight
# through on the first end-to-end run, and the test suite now holds both forms.
AGENTE = "site-auditor"

# Tools that can write. Anything else the auditor holds (Read, Grep, Glob,
# WebFetch) reads by construction and never reaches this file.
SCRITTURA = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Task", "Agent"}

# Commands that read and do nothing else. Absence from this list is a refusal,
# so an interpreter nobody listed (python3, node, sh, awk, sed, xargs, tee) is
# refused without anybody having to predict it.
LETTURA = {
    "basename", "cat", "cd", "curl", "cut", "date", "dig", "dirname", "echo",
    "false", "file", "find", "gh", "git", "grep", "head", "host", "jq", "ls",
    "nslookup", "printf", "pwd", "rg", "sort", "stat", "tail", "tr", "true",
    "uniq", "wc", "which", "whois",
}

# git subcommands that only read. `fetch` is missing on purpose: it touches the
# network and moves refs, and the promise is that an audit leaves the repo as it
# found it.
GIT_LETTURA = {
    "blame", "branch", "cat-file", "check-ignore", "config", "count-objects",
    "describe", "diff", "diff-tree", "for-each-ref", "grep", "log", "ls-files",
    "ls-remote", "ls-tree", "merge-base", "name-rev", "remote", "rev-list",
    "rev-parse", "shortlog", "show", "show-ref", "status", "symbolic-ref",
    "tag", "whatchanged",
}

# Read-only subcommands that turn into writes with the wrong flag. `git branch
# -d` deletes, `git remote add` rewrites the remote an audit is measured
# against, and `git config user.email you@example.com` sets a value.
GIT_FLAG_SCRITTURA = {
    "branch": {"-d", "-D", "-m", "-M", "-c", "-C", "-f", "--force", "--delete",
               "--move", "--copy", "--set-upstream", "--set-upstream-to",
               "--unset-upstream", "--edit-description"},
    "tag": {"-d", "-D", "-a", "-s", "-f", "--delete", "--force", "--annotate", "--sign"},
    "symbolic-ref": {"-d", "--delete"},
    "config": {"--unset", "--unset-all", "--add", "--edit", "-e", "--replace-all", "--rename-section"},
    "remote": {"add", "remove", "rm", "rename", "set-url", "set-head", "set-branches", "prune", "update"},
}

# git options that run before the subcommand. `-c` can set a config value that
# makes git run a command of its own, so reading it as harmless is a mistake.
GIT_GLOBALI_INNOCUE = {"-C", "--no-pager", "-P", "--git-dir", "--work-tree", "--literal-pathspecs"}
GIT_GLOBALI_CON_VALORE = {"-C", "--git-dir", "--work-tree"}

# curl writes a file with these, and sends a request body with those. Filling in
# somebody's contact form counts as changing their site, and it also mails a
# real person.
CURL_SCRIVE = {"-o", "--output", "-O", "--remote-name", "--create-dirs", "--dump-header", "-D",
               "--trace", "--trace-ascii", "--cookie-jar", "-c", "--output-dir", "--remote-header-name",
               "--libcurl", "--etag-save", "--stderr",
               # A config file is a second command line living in a file, and
               # nothing here can read what is in it.
               "-K", "--config"}
CURL_INVIA = {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
              "-F", "--form", "--form-string", "-T", "--upload-file", "--json"}
CURL_METODI_LETTURA = {"GET", "HEAD"}

FIND_SCRIVE = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0",
               "-fprintf", "-fls"}

# What separates one command from the next. Everything else made of punctuation
# is a redirection, a subshell or a background job, and each of those is a way
# to write while looking like a read.
SEPARATORI = {";", "&&", "||", "|", "\n"}


class Rifiuto(Exception):
    """Why a command will not run. The text reaches the model as the refusal."""


def e_l_auditor(tipo: object) -> bool:
    """Whether this tool call came from the auditor, named either way.

    An agent called site-auditor in some other plugin would land here too and
    be held to reading. That is the direction to be wrong in.
    """
    return isinstance(tipo, str) and tipo.rsplit(":", 1)[-1] == AGENTE


def nudo(t: str) -> str:
    """A token without the quotes it was written with."""
    if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    return t


def token(comando: str) -> list[str]:
    # Quotes are kept, which is the point: a quoted `">"` is text somebody is
    # grepping for, and a bare `>` writes a file. Stripping them first would
    # make those two the same token.
    lex = shlex.shlex(comando, posix=False, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        raise Rifiuto(
            "this command could not be read as a shell command, the quotes look "
            "unbalanced, so it is refused rather than guessed at"
        )


def segmenti(comando: str) -> list[list[str]]:
    """The simple commands inside one line, with every way to write refused."""
    fuori: list[list[str]] = []
    corrente: list[str] = []
    lista = token(comando)
    i = 0
    while i < len(lista):
        t = lista[i]
        i += 1
        if t in SEPARATORI:
            if corrente:
                fuori.append(corrente)
            corrente = []
            continue
        if t in {">", ">>"}:
            # Sending output to /dev/null writes nothing anywhere, and it is how
            # you read a status code without keeping the page.
            bersaglio = nudo(lista[i]) if i < len(lista) else ""
            if bersaglio == "/dev/null":
                i += 1
                continue
            raise Rifiuto(
                f"`{t} {bersaglio}` writes a file, and the auditor reads. Send it to "
                "/dev/null if what you want is the status code"
            )
        if t and set(t) <= set(";&|<>()"):
            raise Rifiuto(
                f"`{t}` redirects, groups or backgrounds a command, and an audit that "
                "reads has no use for any of those"
            )
        if "`" in t or "$(" in t:
            raise Rifiuto(
                "a command substitution hides what actually runs, so it is refused here"
            )
        corrente.append(t)
    if corrente:
        fuori.append(corrente)
    return fuori


def controlla_git(argomenti: list[str]) -> None:
    resto = [nudo(a) for a in argomenti]
    while resto and resto[0].startswith("-"):
        opzione = resto.pop(0)
        nome = opzione.split("=", 1)[0]
        if nome not in GIT_GLOBALI_INNOCUE:
            raise Rifiuto(
                f"`git {opzione}` runs before the subcommand and can change what git does, "
                "including running a command of its own"
            )
        if nome in GIT_GLOBALI_CON_VALORE and "=" not in opzione and resto:
            resto.pop(0)
    if not resto:
        return
    sotto, argomenti_sotto = resto[0], resto[1:]
    if sotto not in GIT_LETTURA:
        raise Rifiuto(
            f"`git {sotto}` is not one of the git commands that only read. "
            "The auditor reports what is live, it does not stage, commit, push or deploy"
        )
    vietati = GIT_FLAG_SCRITTURA.get(sotto, set())
    for a in argomenti_sotto:
        if a.split("=", 1)[0] in vietati:
            raise Rifiuto(f"`git {sotto} {a}` writes, and the auditor only reads")
    if sotto == "config" and not any(
        a.startswith(("--get", "--list", "-l")) for a in argomenti_sotto
    ):
        raise Rifiuto(
            "`git config` is allowed for reading a value (--get, --get-all, --list), "
            "and setting one is a change to the repo"
        )


def controlla_curl(argomenti: list[str]) -> None:
    argomenti = [nudo(a) for a in argomenti]
    for i, a in enumerate(argomenti):
        nome = a.split("=", 1)[0]
        if nome in CURL_SCRIVE:
            valore = argomenti[i + 1] if i + 1 < len(argomenti) else ""
            if nome in {"-o", "--output"} and valore == "/dev/null":
                continue
            raise Rifiuto(
                f"`curl {a}` saves the response to a file. To read a status code without "
                'writing anything, use `curl -sS -o /dev/null -w "%{http_code}"`'
            )
        if nome in CURL_INVIA:
            raise Rifiuto(
                f"`curl {a}` sends a request body. Reaching a form means checking that it "
                "is wired up, and submitting it mails a real person"
            )
        if nome in {"-X", "--request"}:
            metodo = argomenti[i + 1] if i + 1 < len(argomenti) else ""
            if metodo.upper() not in CURL_METODI_LETTURA:
                raise Rifiuto(
                    f"`curl -X {metodo}` asks the live site to change something. "
                    "An audit asks and reads the answer"
                )


def controlla_gh(argomenti: list[str]) -> None:
    argomenti = [nudo(a) for a in argomenti]
    if not argomenti or argomenti[0] != "api":
        raise Rifiuto(
            "`gh` is allowed for `gh api` read requests, which is how you ask whether a "
            "deploy landed. The rest of gh opens, closes and merges things"
        )
    for i, a in enumerate(argomenti[1:]):
        nome = a.split("=", 1)[0]
        if nome in {"-f", "-F", "--field", "--raw-field", "--input"}:
            raise Rifiuto(f"`gh api {a}` sends a body, which turns the request into a write")
        if nome in {"-X", "--method"}:
            metodo = argomenti[i + 2] if i + 2 < len(argomenti) else ""
            if metodo.upper() not in CURL_METODI_LETTURA:
                raise Rifiuto(f"`gh api -X {metodo}` is a write request")


def controlla_sort(argomenti: list[str]) -> None:
    # `sort -o` writes where it read, which is the one way this reader writes.
    for a in (nudo(x) for x in argomenti):
        if a.split("=", 1)[0] in {"-o", "--output"}:
            raise Rifiuto(f"`sort {a}` writes its result to a file")


def controlla_find(argomenti: list[str]) -> None:
    for a in (nudo(x) for x in argomenti):
        if a in FIND_SCRIVE:
            raise Rifiuto(f"`find {a}` deletes files or runs a command on each one")


CONTROLLI = {
    "git": controlla_git,
    "curl": controlla_curl,
    "gh": controlla_gh,
    "find": controlla_find,
    "sort": controlla_sort,
}


def esamina(comando: str) -> None:
    """Raise Rifiuto when this command line can do anything except read."""
    parti = segmenti(comando)
    if not parti:
        raise Rifiuto("there is no command here to run")
    for parte in parti:
        programma = nudo(parte[0])
        if "=" in programma and not programma.startswith("/"):
            raise Rifiuto(
                f"`{programma}` sets a variable for the command that follows, which changes "
                "how that command behaves. Write the command on its own"
            )
        nome = programma.rsplit("/", 1)[-1]
        if nome not in LETTURA:
            raise Rifiuto(
                f"`{nome}` is not one of the commands the auditor may run. The list holds "
                "commands that read: curl, git status and its read-only relatives, grep, "
                "find, jq, and the usual text tools. Anything that can write a file or run "
                "code of its own is left out, an interpreter included"
            )
        controllo = CONTROLLI.get(nome)
        if controllo:
            controllo(parte[1:])


def nega(motivo: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"varo keeps the site-auditor read-only, and the harness is what holds "
                    f"it there: {motivo}. Report what you found and say which check you "
                    f"could not run. A gap you name is worth more than a report that reads "
                    f"clean."
                ),
            }
        },
        sys.stdout,
    )


def main() -> int:
    try:
        dati = json.load(sys.stdin)
        fuori_posto = not isinstance(dati, dict) or not e_l_auditor(dati.get("agent_type"))
    except Exception:  # noqa: BLE001
        fuori_posto = True
    if fuori_posto:
        # Either this is not the auditor, or the payload cannot be read at all.
        # Both end the same way, silence, because this hook sees every shell
        # call in the session and publishing is the other half of this plugin.
        return 0

    strumento = dati.get("tool_name", "")
    if strumento in SCRITTURA:
        nega(f"`{strumento}` changes files or hands the work to an agent that can")
        return 0
    if strumento != "Bash":
        return 0

    comando = (dati.get("tool_input") or {}).get("command")
    if not isinstance(comando, str) or not comando.strip():
        nega("a shell call arrived with no command to read")
        return 0

    try:
        esamina(comando)
    except Rifiuto as e:
        nega(str(e))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        # A crash here would let the call through, which is the whole thing this
        # file exists to stop. So a crash refuses, and says why.
        nega(f"the read-only check itself failed ({type(e).__name__}), so nothing runs")
        sys.exit(0)
