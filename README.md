# varo

A Claude Code plugin for shipping static sites and keeping them honest.

Every static site exists twice: the copy in the folder and the copy people
load. They start identical and come apart quietly. Almost every tool checks the
folder. This one checks what is actually live, because that is the copy that
matters and the one nobody looks at.

## The four ways a site lies to you

These are not hypotheticals. Each one was found on a site that was already
online, serving real visitors, while every local check stayed green.

**An endpoint that exists in the code and answers 405 in production.** Its
folder was set aside during a move between hosts and never came back. The form
still submits. The page still says thank you. Nothing arrives, for months.

**A developer's own address hardcoded where config belongs.** Put in during
testing, never taken out. The site sends its mail perfectly, to the wrong
person.

**Security headers written for a host that does not serve the site.** The repo
was forked from a template built for a different platform. The config file is
right there in the root, it reads correctly, and the live host has never opened
it.

**A build step pointing at a folder this host never creates.** The minifier
finds zero files, reports success, exits 0. Nothing is minified and the log
says everything is fine.

Plus the one that hides best: **work committed, pushed, and never deployed**,
because the branch is not the one the host builds. Nothing is lost. Nothing is
live either.

## What you get

**A skill** that knows the hosts and their traps. Which config file belongs to
whom, why GitHub Pages silently drops folders starting with an underscore, how
to tell a deploy that succeeded from a deploy that served the old build.

**An auditor agent** that reports only what the live site confirmed. It fetches
before it claims. It reads and never writes, so pointing it at a client's site
in production is safe.

**A SessionStart hook** that says where you stand before you ask. Which host,
the public address, which branch deploys, how many commits are pushed and not
published. It reads locally and touches no network, so it costs milliseconds
and stays quiet in every session that is about something else.

That last part matters. A hook that speaks in every session is noise people
learn to skip.

**A second hook that makes the auditor's read-only claim true.** The agent
holds a shell, because reading a live site means asking for status codes and
headers and asking git which branch deploys. A shell that can do that can also
push. So every command the auditor sends is read first, and it runs only if it
is one of the commands that read. Writing, staging, committing, pushing,
deploying, posting a form, and any interpreter that could do those in one line,
all come back refused with the reason.

It answers for that one agent. Publishing from a normal session goes through
untouched, which is the other half of this plugin.

## Installing

```bash
claude plugin marketplace add nerln/varo
claude plugin install varo@varo
```

Or clone it and load it for one session, which is the quickest way to see
whether you want it:

```bash
git clone https://github.com/nerln/varo.git
claude --plugin-dir ./varo
```

Nothing to build, and no dependency past Python 3 and git, both already on any
machine that deploys websites.

It costs about 288 tokens in every session, which is the skill and the agent
announcing that they exist. Both hooks run in the harness and add nothing to
the model's context at all. Numbers from `claude plugin details varo`, not
estimated by hand.

## Using it

Open Claude Code in a folder holding a site. The hook speaks first:

![The SessionStart hook reporting two problems before anybody has typed a word](docs/img/hook.png)

Two findings before anybody has typed a word, of the kind that stay true for
weeks because nothing inside the editor ever shows them.

(That picture is made from invented data by `docs/img/hook.html`, so it can be
regenerated and it carries nobody's real site.)

From there:

- "publish it" runs the deploy and then checks that the deploy landed
- "audit the site" hands it to the auditor agent
- "why is my change not showing" usually has its answer in the hook output

## The rule the whole thing runs on

**Fetch it. Do not infer it.**

A file in a functions folder does not mean the endpoint is deployed. A header
in a config file does not mean the host sends it. A build script exiting 0 does
not mean it did anything. Each of those has shipped broken while the repository
looked correct, which is why a finding counts here when the live site answered,
and counts for nothing when it came from reading code and reasoning about what
the code probably does.

## A promise nobody can check is prose

The auditor's description said it changes nothing, and that was a sentence in a
prompt. The agent held a shell, and a shell stages, commits, pushes and deploys.
Nothing in the harness stopped it. The promise was worth whatever the model made
of the instruction that day, and a page fetched during an audit could carry an
instruction of its own.

Now every command the auditor sends is read before it runs, and it runs only if
it is one of the commands that read. The list is an allowlist, because a list of
forbidden commands is a list of the ones somebody thought of, and
`sh -c 'git push'` is never on it.

The check ships with the claim. `tools/prova.py` fails when an agent here calls
itself read-only while holding a tool that writes, unless the refusal exists,
and it runs the refusal against a write to see it land. Take the hook away and
the tests go red.

The first end-to-end run found the guard doing nothing at all. Installed as a
plugin, an agent is called `varo:site-auditor`, and the check was looking for
`site-auditor`, so a write went straight to disk. That is the same mistake in a
smaller size: something believed instead of run. Both spellings are in the tests
now, and the run that proved it works is a run against the live plugin.

## Does the auditor actually find anything

It was pointed at a live site on its first run. It fetched every file the site
serves and diffed it against the working tree, filled the form in a headless
browser and caught the address before anything was sent, checked that address
for a mail server, and loaded the site at phone width.

It reported no drift between repo and production, which was the truth, and then
found something nobody had thought to look for: a folder was reachable on the
live site, returning 200, and permanently broken there. Its dependencies are in
`.gitignore`, so they never reach the host, while the page that needs them
ships every time. Locally it works. On the deployed site it can never work.

It also listed what it could not close, including that it never sent a real
message to anybody, so the mail finding stops at the address and does not claim
delivery. A gap somebody names is worth more than a report that reads clean.

## What it does not do

No servers, no databases, no build system of its own. It works on files a host
serves, plus the small functions a host runs alongside them. When something
needs a real backend, it says so instead of stretching.

It also does not deploy on its own initiative. Publishing stays a step somebody
asks for.

## Checks

```bash
python3 tools/prova.py
```

Forty-five of them, a few seconds, run against throwaway repositories built on
the spot. They cover the plugin manifest, the SessionStart hook's behaviour on a
site, on a folder that is not a site, outside git, and on a path that does not
exist, and what the auditor is allowed to run: pushes, commits, redirections,
interpreters, form submissions and the write hidden at the end of a compound
command all have to come back refused, while curl and the reading half of git
have to come through. They also run the prose through `tools/stylecheck.py`,
which enforces the writing rules mechanically instead of by rereading.

## Licence

GPL-3.0.
