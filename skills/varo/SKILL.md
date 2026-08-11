---
name: varo
description: >-
  Ship and look after a static site: work out which host serves it, publish it,
  and check what is actually live rather than what the repo says. Use it when
  someone opens a folder holding a website, when they ask to publish, deploy,
  put something online, set up hosting or a domain, and when they ask whether
  the site works, whether a form arrives, or why a change is not showing.
  Also for "is the site up", "pubblica il sito", "deploy", "check the site".
---

# varo

A static site has two versions: the one in the folder and the one people load.
They start the same and come apart quietly. A branch gets pushed to the wrong
place, a form points at whoever wrote it, a config file belongs to the host the
template came from. Nothing fails loudly. Everything local stays green.

The job here is to keep those two versions the same, and the way to do that is
to look at the live one.

## First, know where you are

The SessionStart hook has probably already said: the host, the public address,
which branch deploys, what is committed and not published. If it said nothing,
either this is not a site or git cannot see it.

Work out the host from what is on disk:

| On disk | Host |
|---|---|
| `wrangler.toml`, `wrangler.jsonc` | Cloudflare |
| `netlify.toml` | Netlify |
| `vercel.json` | Vercel |
| `.nojekyll`, `_config.yml` | GitHub Pages |
| `_headers`, `_redirects` | Cloudflare or Netlify, they share the format |
| `CNAME` | a custom domain, on any of them |

**Several of these together is a finding, not a puzzle.** A repo that started
from a template carries the old host's config. The new host does not read it,
so every redirect and every security header written there does nothing, and
looks done.

Never guess the public address from the git remote alone. A repo on GitHub can
serve from Cloudflare, and a `github.io` link printed for that site has never
worked once.

## Then look at what is live

Read the deployed site before changing anything. `curl` is enough and it is
the whole point: this is the only step that can disagree with the repo.

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://the-site/        # it answers
curl -sSI https://the-site/ | grep -i "content-security-policy\|strict-transport"
curl -sS https://the-site/ | grep -o "<title>[^<]*</title>"
```

If the repo has server-side endpoints, call each one. Do not read the folder
they live in and assume they shipped.

```bash
curl -sS -o /dev/null -w "%{http_code} %{url_effective}\n" https://the-site/api/whatever
```

## What to check, and why each one is here

Every item below has cost somebody a real site. None of them shows up in a
local build.

1. **Endpoints that answer 404 or 405 while the code says they exist.**
   The usual cause is a folder that was renamed or set aside during a move
   between hosts. The form still posts, the page still says thank you, and
   nothing arrives.

2. **A person's own address left in what should be config.** Test values get
   hardcoded during development and outlive the test. The site sends mail
   successfully, to the developer, for months.

3. **Config written for a host that does not serve this site.** See the table
   above. Check that the file the live host actually reads is the one carrying
   the headers and redirects.

4. **Build steps pointing at a path the host never creates.** A minifier that
   looks in another platform's output folder finds zero files, reports success,
   and does nothing. Read what the build step printed, not that it exited 0.

5. **Leftovers from the template, in public.** Demo pages, a `<title>` still
   naming the theme, docs in seven languages nobody wrote. Check the sitemap
   for pages nobody meant to publish.

6. **Work committed, pushed, and never deployed.** The branch is not the one
   the host builds. Everything looks saved because it is saved. Compare against
   the deploy branch, not against your own upstream.

7. **Missing security headers.** Cheap to add, invisible when absent.

8. **Forms that accept and deliver nowhere.** Submit one yourself and wait for
   it to arrive. This is the single thing most worth doing by hand.

## Publishing

Publishing is a deliberate step, always separate from saving files. Say what
changes, then push.

```bash
git status --short          # look before staging
git add -A && git commit -m "..." && git push
```

Then check the deploy landed, rather than trusting that a push means a
deployment:

```bash
gh api repos/OWNER/REPO/pages/builds/latest --jq '{status, commit: .commit[0:7]}'
curl -sS -o /dev/null -w "%{http_code}\n" https://the-site/
```

Two traps that cost an evening each:

- **GitHub Pages drops any folder starting with `_`.** Site loads, no styling.
  An empty `.nojekyll` at the root fixes it.
- **A deploy that reports success can still serve the old build.** Ask for the
  commit the deployment used and compare it with the one you pushed.

## Setting up a new site

For a site that is not online yet, in order: a repo, a host, the address,
then content. Free and enough for anything static: GitHub Pages (repo settings,
deploy from a branch) or Cloudflare Pages (connect the repo, or drag the folder
in). Both give a working address in about a minute.

Custom domains cost around ten to fifteen a year and attach free to either.
Domains that cost nothing are no longer a real option.

## When to send in the auditor

For a full pass over a live site, hand it to the `site-auditor` agent. It reads
and reports, and changes nothing, so it is safe to point at a client's site in
production. That last part is held by a hook rather than by the agent's own
good behaviour: every shell command the auditor sends is checked first, and one
that writes, stages, commits, pushes, deploys or posts a form is refused before
it runs. Use the auditor before handing a site over, after moving hosts, and
when someone says a form stopped arriving.

Publishing from a normal session is untouched by that check. It answers for the
auditor and stays silent everywhere else.

## What this does not do

It does not manage servers, databases, or anything that needs one. A static
site is files a host serves, plus at most the small functions a host runs for
you. When a request needs a real backend, say so plainly rather than stretching
this.
