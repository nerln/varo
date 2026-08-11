#!/usr/bin/env python3
"""Check varo before it goes out.

Three things get checked here. That the plugin is shaped the way Claude Code
expects, because a typo in a manifest fails silently and the plugin simply
never loads. That the hook behaves on real repositories: it has to speak where
there is a site, stay quiet where there is not, and never take a session down
with it.

And that no agent here promises something the harness does not hold it to. An
agent that says it only reads, while holding a tool that writes, is asking to
be believed. The checks below refuse to let that ship: where the promise is
made, the refusal has to be real, and it gets run to see that it is.

    python3 tools/prova.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
HOOK = RADICE / "hooks" / "stato.py"
GUARDIA = RADICE / "hooks" / "solo-lettura.py"

# Tools that can change something, straight away or by handing the work to an
# agent that can. Holding one of these is what turns a read-only claim into a
# claim somebody has to hold you to.
STRUMENTI_SCRITTURA = ["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Task", "Agent"]

# How an agent says, in its own words, that it changes nothing.
PROMESSE = [
    "read-only", "read only", "reads and reports", "reads and never writes",
    "changes nothing", "makes no change", "never writes", "pushes nothing",
]

passate = 0
fallite: list[str] = []


def prova(nome: str, condizione: bool, dettaglio: str = "") -> None:
    global passate
    if condizione:
        passate += 1
        print(f"  ok   {nome}")
    else:
        fallite.append(f"{nome}{': ' + dettaglio if dettaglio else ''}")
        print(f"  NO   {nome}{': ' + dettaglio if dettaglio else ''}")


def esegui_hook(cwd: Path | str) -> tuple[str, int]:
    """Run the hook the way Claude Code does, and give back stdout and rc."""
    out = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return out.stdout.strip(), out.returncode


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)


def frontmatter(path: Path) -> dict[str, str]:
    """The frontmatter of an agent file, without asking for a yaml library.

    Enough for name, description and tools, which is where a promise and a tool
    grant are written. A folded value carries on over indented lines.
    """
    testo = path.read_text(encoding="utf-8")
    if not testo.startswith("---"):
        return {}
    corpo = testo.split("---", 2)
    if len(corpo) < 3:
        return {}
    campi: dict[str, str] = {}
    chiave = None
    for riga in corpo[1].splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", riga)
        if m:
            chiave = m.group(1)
            valore = m.group(2).strip()
            campi[chiave] = "" if valore in {">-", ">", "|", "|-"} else valore
        elif chiave and riga.strip():
            campi[chiave] = (campi[chiave] + " " + riga.strip()).strip()
    return campi


def guardia(comando: str, *, agente: str = "varo:site-auditor", strumento: str = "Bash") -> str:
    """Run the read-only hook on one command and give back its decision."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": strumento,
        "tool_input": {"command": comando},
    }
    if agente:
        payload["agent_type"] = agente
    out = subprocess.run(
        [sys.executable, str(GUARDIA)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if out.returncode != 0:
        return f"errore rc={out.returncode}"
    if not out.stdout.strip():
        return "passa"
    try:
        return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"]
    except (json.JSONDecodeError, KeyError):
        return f"uscita illeggibile: {out.stdout[:60]}"


def copre(hooks: dict, evento: str, strumento: str) -> bool:
    """Whether a hook is wired to fire for this tool, matched as Claude Code does."""
    for gruppo in hooks.get("hooks", {}).get(evento, []):
        pattern = gruppo.get("matcher", "")
        if not pattern:
            return True
        try:
            if re.search(pattern, strumento):
                return True
        except re.error:
            continue
    return False


def sito_finto(base: Path, *, con_config: list[str] = (), pagina: str = "index.html") -> Path:
    """A throwaway repo holding a site, so the checks touch nothing real."""
    d = base
    d.mkdir(parents=True, exist_ok=True)
    (d / pagina).parent.mkdir(parents=True, exist_ok=True)
    (d / pagina).write_text("<!doctype html><title>prova</title>", encoding="utf-8")
    for nome in con_config:
        (d / nome).write_text("", encoding="utf-8")
    git(["init", "-q", "-b", "main"], d)
    git(["config", "user.email", "prova@example.com"], d)
    git(["config", "user.name", "Prova"], d)
    git(["add", "-A"], d)
    git(["commit", "-qm", "primo"], d)
    return d


def main() -> int:
    print("\nManifesto e struttura\n")

    manifesto = RADICE / ".claude-plugin" / "plugin.json"
    prova("il manifesto esiste", manifesto.exists())
    dati = {}
    if manifesto.exists():
        try:
            dati = json.loads(manifesto.read_text(encoding="utf-8"))
            prova("il manifesto è json valido", True)
        except json.JSONDecodeError as e:
            prova("il manifesto è json valido", False, str(e))
    for campo in ("name", "version", "description"):
        prova(f"il manifesto ha {campo}", bool(dati.get(campo)))

    hooks = RADICE / "hooks" / "hooks.json"
    prova("hooks.json esiste", hooks.exists())
    if hooks.exists():
        try:
            h = json.loads(hooks.read_text(encoding="utf-8"))
            prova("hooks.json è json valido", True)
            prova("l'hook si aggancia a SessionStart", "SessionStart" in h.get("hooks", {}))
            testo = hooks.read_text(encoding="utf-8")
            prova(
                "l'hook usa CLAUDE_PLUGIN_ROOT invece di un percorso fisso",
                "${CLAUDE_PLUGIN_ROOT}" in testo,
            )
        except json.JSONDecodeError as e:
            prova("hooks.json è json valido", False, str(e))

    mercato = RADICE / ".claude-plugin" / "marketplace.json"
    prova("marketplace.json esiste", mercato.exists())
    if mercato.exists():
        try:
            m = json.loads(mercato.read_text(encoding="utf-8"))
            prova("marketplace.json è json valido", True)
            nomi = [p.get("name") for p in m.get("plugins", [])]
            prova("il marketplace elenca varo", "varo" in nomi, str(nomi))
        except json.JSONDecodeError as e:
            prova("marketplace.json è json valido", False, str(e))

    prova("la skill c'è", (RADICE / "skills" / "varo" / "SKILL.md").exists())
    prova("l'agente c'è", (RADICE / "agents" / "site-auditor.md").exists())

    for f in (RADICE / "skills" / "varo" / "SKILL.md", RADICE / "agents" / "site-auditor.md"):
        if f.exists():
            testo = f.read_text(encoding="utf-8")
            prova(f"{f.name} ha il frontmatter", testo.startswith("---"))
            prova(f"{f.name} dichiara name e description",
                  "name:" in testo[:400] and "description:" in testo[:400])

    print("\nL'hook su repository veri\n")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        sito = sito_finto(base / "sito", con_config=[".nojekyll"])
        out, rc = esegui_hook(sito)
        prova("esce senza errore su un sito", rc == 0, f"rc={rc}")
        prova("su un sito dice qualcosa", bool(out))
        if out:
            try:
                testo = json.loads(out)["hookSpecificOutput"]["additionalContext"]
                prova("l'uscita ha la forma che Claude Code legge", True)
                prova("riconosce GitHub Pages", "GitHub" in testo)
            except (json.JSONDecodeError, KeyError) as e:
                prova("l'uscita ha la forma che Claude Code legge", False, str(e))

        # Una cartella senza pagine non è un sito: deve tacere, perché quasi
        # tutte le sessioni non parlano di siti e un hook che parla comunque
        # diventa rumore che si impara a saltare.
        muto = base / "muto"
        muto.mkdir()
        (muto / "note.txt").write_text("niente", encoding="utf-8")
        git(["init", "-q"], muto)
        out, rc = esegui_hook(muto)
        prova("tace dove non c'è un sito", out == "" and rc == 0, out[:60])

        # Fuori da git non c'è niente da dire, e non deve rompersi.
        fuori = base / "fuori"
        fuori.mkdir()
        (fuori / "index.html").write_text("<!doctype html>", encoding="utf-8")
        out, rc = esegui_hook(fuori)
        prova("tace fuori da un repository", out == "" and rc == 0)

        # Una cartella che non esiste: capita con sessioni riprese da altrove.
        out, rc = esegui_hook(base / "questa-non-esiste")
        prova("non si rompe su una cartella inesistente", rc == 0, f"rc={rc}")

        # Il caso che ha fatto nascere lo strumento: config di più host insieme.
        molti = sito_finto(base / "molti", con_config=["vercel.json", "netlify.toml"])
        out, _ = esegui_hook(molti)
        prova(
            "segnala config di più host nello stesso repo",
            "more than one host" in out,
        )

        # Un sito tenuto in site/ o docs/: è comunque un sito da mantenere.
        annidato = sito_finto(base / "annidato", pagina="site/index.html")
        out, _ = esegui_hook(annidato)
        prova("trova un sito dentro site/", bool(out))

        # Nessun indirizzo inventato quando l'host non è GitHub Pages: stampare
        # un link che non ha mai funzionato è peggio che non stamparne nessuno.
        cf = sito_finto(base / "cloudflare", con_config=["wrangler.toml"])
        git(["remote", "add", "origin", "https://github.com/tale/quale.git"], cf)
        out, _ = esegui_hook(cf)
        prova("non inventa un indirizzo github.io su Cloudflare",
              "github.io" not in out, out[:80])

    print("\nSola lettura: chi tiene la promessa\n")

    prova("il guardiano di sola lettura c'è", GUARDIA.exists())

    ganci: dict = {}
    if hooks.exists():
        try:
            ganci = json.loads(hooks.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            ganci = {}

    # Il controllo che questo progetto deve avere: una promessa parte solo
    # insieme a ciò che la verifica. Se la descrizione di un agente dice che
    # legge e basta, e l'agente tiene uno strumento che scrive, allora quel
    # rifiuto deve esistere davvero e viene eseguito qui per vederlo.
    for f in sorted((RADICE / "agents").glob("*.md")):
        campi = frontmatter(f)
        nome = campi.get("name") or f.stem
        promessa = next((p for p in PROMESSE if p in f.read_text(encoding="utf-8").lower()), None)
        concessi = [t.strip() for t in campi.get("tools", "").split(",") if t.strip()]
        pericolosi = [t for t in concessi if t in STRUMENTI_SCRITTURA]

        if not promessa:
            prova(f"{nome}: non promette sola lettura, niente da tenere", True)
            continue
        if not pericolosi:
            prova(f"{nome}: promette sola lettura e non ha strumenti che scrivono", True)
            continue
        # Installato come plugin, l'agente si presenta come `varo:site-auditor`.
        # Caricato da una cartella durante lo sviluppo può presentarsi nudo. La
        # prima prova vera è passata proprio di qui: la guardia cercava il nome
        # nudo e un `echo prova > file` è finito su disco.
        pacchetto = dati.get("name") or "varo"
        for strumento in pericolosi:
            prova(
                f"{nome}: promette \"{promessa}\" e {strumento} passa da un hook PreToolUse",
                copre(ganci, "PreToolUse", strumento),
                "la descrizione promette sola lettura mentre la harness lascia scrivere",
            )
            for chiamato in (nome, f"{pacchetto}:{nome}"):
                prova(
                    f"{nome}: il rifiuto di {strumento} è reale come `{chiamato}`",
                    guardia("git push", agente=chiamato, strumento=strumento) == "deny",
                    "hook agganciato ma il comando passa lo stesso",
                )

    def tutti_negati(nome: str, comandi: list[str]) -> None:
        esiti = {c: guardia(c) for c in comandi}
        passati = [c for c, e in esiti.items() if e != "deny"]
        prova(nome, not passati, f"passa: {passati}")

    def tutti_permessi(nome: str, comandi: list[str]) -> None:
        esiti = {c: guardia(c) for c in comandi}
        fermati = [f"{c} -> {e}" for c, e in esiti.items() if e != "passa"]
        prova(nome, not fermati, f"fermati: {fermati}")

    tutti_negati("nega push, commit, add, deploy, fetch e config scritta", [
        "git push",
        "git commit -am wip",
        "git add -A",
        "npx wrangler deploy",
        "gh pr merge 3",
        "git fetch",
        "git remote add origin https://example.com/sito.git",
        "git config user.email chi@example.com",
    ])

    tutti_negati("nega la scrittura di un file, anche di sbieco", [
        "echo x > index.html",
        "cat index.html > copia.html",
        "curl -o pagina.html https://esempio.it/",
        "curl -sS https://esempio.it/ | tee scaricato.html",
        "sed -i s/a/b/ index.html",
        "find . -name '*.html' -delete",
        "sort -o ordinato.txt pagine.txt",
        # Un file di configurazione di curl è una seconda riga di comando che
        # vive in un file, e può portarsi dentro un -o.
        "curl -K istruzioni.conf https://esempio.it/",
    ])

    # Il buco che una lista di comandi vietati non chiude mai: l'interprete.
    # `sh -c 'git push'` non contiene niente che una lista del genere cerchi.
    tutti_negati("nega gli interpreti, che farebbero tutto in una riga", [
        "sh -c 'git push'",
        "bash pubblica.sh",
        "python3 -c 'open(\"index.html\",\"w\")'",
        "node build.js",
        "awk '{print > \"f\"}' index.html",
        "echo index.html | xargs rm",
    ])

    tutti_negati("nega quello che si nasconde in fondo a un comando composto", [
        "git status && git push",
        "curl -sSI https://esempio.it/ ; git push",
        "git -c core.pager=!sh status",  # stylecheck: allow
        "curl $(cat indirizzo.txt)",
        "curl `cat indirizzo.txt`",
        "AMBIENTE=1 curl https://esempio.it/",
    ])

    # Raggiungere un form vuol dire controllare che sia collegato. Spedirlo vuol
    # dire scrivere a una persona vera, e su un sito di un cliente.
    tutti_negati("nega la spedizione di un form o di una richiesta con un corpo", [
        "curl -X POST --data nome=prova https://esempio.it/api/contatti",
        "curl -F messaggio=@nota.txt https://esempio.it/api/contatti",
        "gh api -X POST repos/tale/quale/pages",
    ])

    tutti_permessi("lascia lavorare l'auditor: fetch, header, git in lettura", [
        'curl -sS -o /dev/null -w "%{http_code}" https://esempio.it/',
        "curl -sSI https://esempio.it/",
        'curl -sS https://esempio.it/ | grep -o "<title>[^<]*</title>"',
        "git rev-list --count origin/main..HEAD",
        "git status --porcelain",
        "git remote get-url origin",
        "git config --get remote.origin.url",
        "git symbolic-ref refs/remotes/origin/HEAD",
        "gh api repos/tale/quale/pages/builds/latest",
        "dig MX esempio.it +short",
        "grep -rn mailto: .",
        "cat index.html 2>/dev/null",
    ])

    # Una redirezione scrive, un `>` fra virgolette è testo che si cerca dentro
    # una pagina. Confonderli fermerebbe un controllo che serve.
    prova("non scambia un > fra virgolette per una redirezione",
          guardia('grep -o ">" index.html') == "passa")

    prova("nega gli strumenti che scrivono, qualunque cosa chiedano",
          all(guardia("", strumento=s) == "deny" for s in ("Write", "Edit", "Task")))

    prova("riconosce l'agente col nome del plugin davanti e senza",
          guardia("git push", agente="varo:site-auditor") == "deny"
          and guardia("git push", agente="site-auditor") == "deny")

    # Pubblicare è l'altra metà di questo plugin, e passa da git che scrive.
    prova("non tocca la sessione principale",
          guardia("git push", agente="") == "passa")
    prova("non tocca un altro agente",
          guardia("git push", agente="altro-agente") == "passa")

    illeggibile = subprocess.run(
        [sys.executable, str(GUARDIA)], input="non è json", capture_output=True, text=True
    )
    prova("con un payload illeggibile tace, invece di fermare la sessione",
          illeggibile.returncode == 0 and illeggibile.stdout.strip() == "",
          illeggibile.stdout[:60])

    print("\nStile\n")

    stylecheck = RADICE / "tools" / "stylecheck.py"
    if stylecheck.exists():
        pubblici = [
            str(RADICE / "README.md"),
            str(RADICE / "skills" / "varo" / "SKILL.md"),
            str(RADICE / "agents" / "site-auditor.md"),
            str(RADICE / "hooks" / "hooks.json"),
            str(HOOK),
            str(GUARDIA),
        ]
        pubblici = [p for p in pubblici if Path(p).exists()]
        out = subprocess.run(
            [sys.executable, str(stylecheck), *pubblici],
            capture_output=True, text=True,
        )
        prova("i testi pubblici passano lo stylecheck", out.returncode == 0,
              (out.stdout + out.stderr).strip()[:400])
    else:
        prova("stylecheck presente", False, "tools/stylecheck.py manca")

    print()
    if fallite:
        print(f"{passate} passate, {len(fallite)} fallite\n")
        for f in fallite:
            print(f"  - {f}")
        return 1
    print(f"{passate} passate, 0 fallite\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
