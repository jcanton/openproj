"""`openproj init`: a plan repository with nothing in it but its configuration.

What a plan needs before its first record is four config files, and every one of
them was being copied out of `seed/` — which is a demo, invented, and says so in
its own README. A copy of the demo's roster is a plan that names people who do
not exist; a copy of its cycle table is a plan whose calendar is the demo's
forever; and the schema version copied along with them is whatever the demo was
at. This writes the same four files with nothing invented in them, at the newest
schema version, and commits them under the git identity of whoever ran it.

The deployment description is optional and lives in the PLAN for a reason: which
plan a service serves, which org may write to it and which cloud project pays for
it are facts about that plan's deployment, and keeping them in the tool's source
made the tool one team's. `gcloud_deploy.sh` reads the file this writes, and
`deploy/example.env` is the same file with every value blank.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .model import LATEST_SCHEMA_VERSION

# The deployment description, one row per key: the name, what it is, and the
# value a fresh plan may assume. `ORG` and `REMOTE` are here as well as on the
# plan because the deploy script reads one file and passes them on to the
# container as `OPENPROJ_ORG` and `OPENPROJ_REMOTE`.
DEPLOY_KEYS: tuple[tuple[str, str, str], ...] = (
    (
        "PROJECT",
        "Google Cloud project ID — the short string `gcloud projects list` prints under\n"
        "PROJECT_ID, not the display name and not the number. Billing has to be enabled\n"
        "on it: Cloud Run, Cloud Build and Artifact Registry all refuse without it, free\n"
        "tier included.",
        "",
    ),
    (
        "REGION",
        "A Tier 1 region, which is what Cloud Run's always-free allowance applies to.\n"
        "Changing it changes the service URL, and with it the OAuth App's redirect URIs.",
        "europe-west1",
    ),
    ("SERVICE", "The Cloud Run service name; it becomes part of the URL.", "openproj"),
    (
        "REMOTE",
        "The plan repository the service clones on boot, serves, and pushes every\n"
        "save to. An https URL; the credential is the GitHub App below.",
        "",
    ),
    ("ORG", "The GitHub org whose membership decides who may write.", ""),
    (
        "APP_ID",
        "The GitHub App the server writes with — its ID, from the App's settings page.\n"
        "Not a secret.",
        "",
    ),
    (
        "INSTALLATION_ID",
        "The number at the end of the URL when you open the App's installation on the\n"
        "plan repository. Not a secret.",
        "",
    ),
    (
        "OAUTH_CLIENT_ID",
        "The OAuth App a person signs in through — its client ID. The client SECRET is\n"
        "asked for at the deploy prompt and goes straight into Secret Manager; it is\n"
        "never written to a file.",
        "",
    ),
    (
        "APP_KEY_FILE",
        "Path on this machine to the GitHub App's private key. Read exactly once, to\n"
        "create the secret; a redeploy leaves an existing secret alone, so once it exists\n"
        "the file can be deleted and this left blank.",
        "",
    ),
)

_ENV_HEADER = """\
# One deployment of openproj, described. `gcloud_deploy.sh <this file>` reads it;
# `openproj init` writes it when asked. It lives in the plan repository, beside the
# plan it deploys, so the tool's own source names no deployment.
#
# Every value here is a name or a public identifier. The two secrets — the App's
# private key and the OAuth client secret — go into Secret Manager at deploy time
# and are never in this file.
"""


def deploy_env_text(values: dict[str, str]) -> str:
    """The deployment file, every key present, the unknown ones blank.

    Blank rather than omitted so that a person filling it in by hand sees every
    question, and so that `deploy/example.env` — this function over an empty
    dict — is the whole form.
    """
    lines = [_ENV_HEADER]
    for key, about, default in DEPLOY_KEYS:
        value = values.get(key, default)
        lines.append("".join(f"# {sentence}\n" for sentence in about.splitlines()))
        lines.append(f'{key}="{value}"\n\n')
    return "".join(lines).rstrip("\n") + "\n"


@dataclass
class Options:
    """What `init` was told, on the command line or at the prompt."""

    org: str = ""
    remote: str = ""
    login: str = ""
    deploy: dict[str, str] = field(default_factory=dict)


def ask_for_the_rest(given: Options, ask: Callable[[str], str]) -> Options:
    """Fill in whatever the command line left out, one question each.

    `ask` is `input` in real life and a scripted answerer in tests. A question is
    only asked when the flag was not given, so a command line that says
    everything asks nothing — which is what makes it safe to call this from a
    terminal and skip it everywhere else.

    The deployment is one yes-or-no and then a question per key; "no" writes no
    deployment file at all rather than a file of blanks, because a plan that is
    only ever served locally should not carry a form nobody will fill in.
    """

    def answer(question: str, default: str = "") -> str:
        hint = f" [{default}]" if default else ""
        said = ask(f"{question}{hint}: ").strip()
        return said or default

    org = given.org or answer("GitHub org whose members may write (blank: none, local use only)")
    remote = given.remote or answer("Remote URL of this plan repository (blank: not yet)")
    login = given.login or answer("Your GitHub login, for the roster (blank: skip)")
    deploy = dict(given.deploy)
    if not deploy and answer("Describe a Cloud Run deployment now? (y/N)", "n").lower() in (
        "y",
        "yes",
    ):
        for key, _, default in DEPLOY_KEYS:
            if key == "ORG":
                deploy[key] = org
            elif key == "REMOTE":
                deploy[key] = remote
            else:
                deploy[key] = answer(key, default)
    return Options(org=org, remote=remote, login=login, deploy=deploy)


def plan_files(name: str, options: Options) -> dict[str, str]:
    """Every file a new plan is made of, keyed by repository-relative path.

    The four config files are the ones `model.CONFIG_FILES` names, and nothing in
    them is invented: the roster is whoever ran the command or nobody, the cycle
    table is empty, the holidays are empty, and the schema version is the newest
    there is, because a plan with no records has nothing to grandfather.
    """
    roster = f"[{options.login}]" if options.login else "[]"
    files = {
        "config/defaults.yaml": f"""\
# schema_version is the version NEW records are created at. Every validation
# rule records the version that introduced it, and a record is only blocked by
# rules whose version is <= its own created_schema_version — so an older plan
# can adopt a new rule without invalidating what was written before it. A new
# plan starts at the newest version, because it has nothing to grandfather.
schema_version: {LATEST_SCHEMA_VERSION}
# The rate one person works at when nobody has said otherwise, as a fraction of
# full time. A size is in PERSON-weeks, so the people on a bet divide it, each at
# their own rate; the cycle files override this per person and per cycle.
nominal_availability: 1.0
# Of each cycle's window, how much is cool-down rather than build. An overrun is
# measured against the end of build.
cooldown_weeks: 2.0
# The repositories this plan's work happens in, as owner/repo, so the editor can
# offer their open pull requests. Empty means it offers only what the plan
# already cites and asks nothing of the network.
repositories: []
""",
        "config/cycles.yaml": """\
# Cycle windows, inclusive: <cycle number>: [first day, last day]. Six weeks of
# build plus the cool-down in defaults.yaml is the usual eight. A window here is
# the calendar; what was bet in a cycle, and who was available for it, is the
# record cycles/<number>.md.
#
#   1: [2026-01-05, 2026-02-27]
cycles: {}
""",
        "config/holidays.yaml": """\
# Non-working days, one date per line. Weekends are already excluded by the
# scheduler, and there is no fractional working day.
holidays: []
""",
        "config/people.yaml": f"""\
# The roster. Names here autocomplete in the UI; a name that is not here is a
# warning rather than a refusal, so a new colleague is assignable on day one.
# Empty means the check is off.
known_people: {roster}
""",
        ".gitignore": """\
# The writer's flock. Every openproj command leaves one beside the plan it ran
# against, holding the pid of whoever last held the lock; it is never a record.
openproj.lock
""",
        "README.md": f"""\
# {name}

The plan. One markdown file per record — the fields in frontmatter, the shaping
document as the body — and git is the database: there is no other copy and no
export step. [openproj](https://github.com/jcanton/openproj) serves and edits
these files, and everything it shows is derived from what is here.

The plan is deliberately separate from the tool's source. A plan commit must not
run the tool's CI, and the credential a server writes with must be structurally
incapable of touching source.

```bash
openproj check .                    # every rule; exits non-zero only on blockers
openproj schedule .                 # the derived dates, one line per record, with the reason
openproj new pitch . --title "…"    # a record, minted and held to every rule before it is written
openproj render . out/              # the pages as static files
git clone --bare . /tmp/plan.git && openproj serve --repo /tmp/plan.git --auth dev
```

`products/`, `projects/`, `pitches/`, `tasks/`, `issues/`, `notes/`, `cycles/`
and `people/` each hold one file per record and nothing below them. `config/`
holds the defaults, the cycle calendar, the holidays and the roster.
""",
    }
    if options.deploy:
        files["deploy/openproj.env"] = deploy_env_text(options.deploy)
    return files
