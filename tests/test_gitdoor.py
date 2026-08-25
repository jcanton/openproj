"""The git door: a file somebody commits by hand that is not a record.

"Edit it in git if you prefer" is the promise the whole store is built on — there
is no working copy precisely so that a human with a terminal can push to the same
repository the server is serving, and `store.head` is read off disk every time so
that their commit is visible at once. This is what happens on the read side when
what they pushed does not parse.

Every one of the fifteen files below took ten of the eleven routes down with a
500 — not the route that touches the file, every route, for everybody,
permanently. `/healthz` alone kept answering, which is how the last two
permanent breakages stayed up on a monitor while the site was dead. One index is
built for all the pages and it was built by parsing every file in the repository
with nothing around the parse: `parse permissively, validate strictly` was true
of the values *inside* a record that loads and of nothing else, so an unknown
status is a Problem beside its row and a missing `---` is the whole site.

That count is measured rather than asserted — the same fifteen were run against
the source as it stood before the fix, off `git archive HEAD`, and every one of
them took the same ten routes.

Three exception families reach that boundary and one of them is an
`AttributeError`, which is why the guard is not a list of the exceptions anybody
has seen yet — see `readable` in `model.py`.

The bar for each case is the same and it is not "a 200": the page has to NAME THE
FILE, because a plan that quietly renders fifteen of its sixteen tasks is worse
than one that fails loudly. Every assertion below reads the banner out of the
parsed document rather than searching the served bytes, since the shell's
stylesheet and comments put plenty of paths and sentences into a page as text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from pages import banner_says, unreadable_in
from test_store import commit_directly
from test_web import PATH, SEED, TASK

from openproj.web import create_app

# Every route a reader can open, plus the two that answer scripts. `/healthz` is
# deliberately in the list: it was the one route that survived the last two
# permanent breakages, and a green healthz over nine dead pages is how one of
# them stayed up for a whole round.
ROUTES = (
    "/", "/graph", "/timeline", "/people", "/cycles", "/cycle/37", "/detail",
    f"/detail/{TASK}", "/new", "/api/index.json", "/healthz",
)

# (what somebody committed, the file it lands in, its content)
BREAKAGES = [
    (
        "a task file with no frontmatter at all",
        "tasks/task-d00001.md",
        "Just some notes I pasted into the folder.\n",
    ),
    (
        "a task file whose YAML never closes its flow sequence",
        "tasks/task-d00002.md",
        "---\nid: task-d00002\nkind: task\ntitle: [unclosed\n---\n\nBody\n",
    ),
    (
        "a file with no kind, whose id names no kind either",
        "tasks/task-d00003.md",
        "---\nid: nonsense\ntitle: A file nobody typed a kind into\n---\n",
    ),
    (
        "an assigned_on that is a phrase",
        "tasks/task-d00004.md",
        "---\nid: task-d00004\nkind: task\ntitle: A date somebody typed\n"
        "status: ready\nowner: ann\nreviewers: [bo]\nperson_weeks: 1\n"
        "assigned_on: next tuesday\n---\n",
    ),
    (
        "a size that is a word",
        "tasks/task-d00005.md",
        "---\nid: task-d00005\nkind: task\ntitle: A size somebody typed\n"
        "status: ready\nowner: ann\nreviewers: [bo]\nperson_weeks: three\n---\n",
    ),
    (
        "a frontmatter that is a list rather than a map",
        "tasks/task-d00006.md",
        "---\n- id: task-d00006\n- kind: task\n---\n\nBody\n",
    ),
    (
        "a cycle record whose YAML never closes",
        "cycles/0039.md",
        "---\ncycle: 39\nstarts_on: [oops\n---\n",
    ),
    (
        "a cycle record with no start date",
        "cycles/0040.md",
        "---\ncycle: 40\nbuild_weeks: 4\n---\n",
    ),
    (
        "a cycle number that is a word",
        "cycles/0041.md",
        "---\ncycle: forty-one\nstarts_on: 2026-09-01\n---\n",
    ),
    (
        "a config file whose YAML never closes",
        "config/people.yaml",
        "known_people: [ann, bo\n",
    ),
    (
        "a holiday that is not a date",
        "config/holidays.yaml",
        "holidays: [not-a-day]\n",
    ),
    (
        "a schema_version that is a word",
        "config/defaults.yaml",
        "schema_version: two\n",
    ),
    (
        "a project file that is empty",
        "projects/proj-d00007.md",
        "",
    ),
    (
        "a pitch whose reviewers are a map",
        "pitches/pitch-d00008.md",
        "---\nid: pitch-d00008\nkind: pitch\ntitle: A shape\nreviewers:\n  bo: yes\n---\n",
    ),
    (
        "a task whose frontmatter is only a comment",
        "tasks/task-d00009.md",
        "---\n# nothing but a note to myself\n---\n\nBody\n",
    ),
    # The sixteenth, and the only one whose bytes are a perfectly good record.
    # What is wrong with it is where it is: a plan directory holds one file per
    # record and does not nest, because `login_of` and `_path_for` read an
    # identity off the filename. The server matched on the FIRST segment of the
    # path and drew it; `load_repo` globbed one level and never saw it. Reported
    # for the same reason as the fifteen above — a file somebody committed that
    # nothing reads is exactly the thing you cannot see is missing.
    (
        "a record filed one directory deeper than records live",
        "tasks/archive/task-d00010.md",
        "---\nid: task-d00010\nkind: task\ntitle: A record somebody filed away\n"
        "status: ready\nowner: ann\nreviewers: [bo]\nperson_weeks: 1\n---\n",
    ),
]

NAMES = [name for name, _, _ in BREAKAGES]


@pytest.fixture
def door(tmp_path: Path):
    """A bare plan repository, and a way to push one bad file into it."""

    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")

    def push(where: str, content: str) -> None:
        commit_directly(path, SEED | {where: content}, f"a person edits {where}")

    return path, push


# --------------------------------------------------------------------------- #
# Every route answers, and every page names the file
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name,where,content", BREAKAGES, ids=NAMES)
def test_a_file_nobody_could_parse_costs_that_file_and_nothing_else(
    door, name: str, where: str, content: str
):
    """Every route answers, and every page that a person reads names the file.

    Two loops and not one. A 200 on its own is the weaker half of the claim and
    the easier half to keep by accident: skipping the file silently gives you
    eleven 200s and a plan quietly short by one task, which is the failure this
    is really about. The second loop is the claim — the reader is told, on
    whatever page they happen to be on, which file is not in what they are
    looking at.
    """
    path, push = door
    push(where, content)

    with TestClient(create_app(path, auth="dev")) as client:
        for route in ROUTES:
            answer = client.get(route)
            assert answer.status_code == 200, f"{route} with {name}: {answer.text[:400]}"
        for route in ROUTES:
            if route in ("/api/index.json", "/healthz"):
                continue
            named = unreadable_in(client.get(route).text)
            assert any(where in line for line in named), (
                f"{route} did not name {where} with {name}; it said {named}"
            )


@pytest.mark.parametrize("name,where,content", BREAKAGES, ids=NAMES)
def test_the_rest_of_the_plan_is_still_on_the_page(door, name: str, where: str, content: str):
    """The danger is not the 500, it is the quiet version of the same thing: a
    table that renders fifteen of sixteen tasks and says nothing."""
    path, push = door
    push(where, content)

    with TestClient(create_app(path, auth="dev")) as client:
        assert "Reproduce the 2-GPU seam artefact" in client.get("/table").text, name
        records = client.get("/api/index.json").json()["plan"]
        assert TASK in records, name


@pytest.mark.parametrize("name,where,content", BREAKAGES, ids=NAMES)
def test_the_json_route_says_which_file_and_why(door, name: str, where: str, content: str):
    """The other consumer. A script reading the plan has to be able to tell "the
    plan holds sixteen tasks" from "the plan holds sixteen tasks that parsed"."""
    path, push = door
    push(where, content)

    with TestClient(create_app(path, auth="dev")) as client:
        answer = client.get("/api/index.json").json()

        assert [one["path"] for one in answer["unreadable"]] == [where], name
        assert answer["unreadable"][0]["why"], "named the file and said nothing about why"


def test_a_plan_everybody_can_read_says_nothing_about_unreadable_files(door):
    """The other half of the claim: no banner at all when there is nothing to say.

    Asserted on the headline as well as on the list, because those are two
    different questions and the list alone cannot tell them apart. Written first
    with only the list, this passed with the `{% if %}` around the section
    deleted — every page in the app carrying an empty red box that said "0 files
    in the plan are not records", which is exactly the state it exists to refuse.
    """
    path, _ = door

    with TestClient(create_app(path, auth="dev")) as client:
        for route in ROUTES:
            if route in ("/api/index.json", "/healthz"):
                continue
            page = client.get(route).text
            assert unreadable_in(page) == [], route
            assert banner_says(page) == "", route
        assert client.get("/api/index.json").json()["unreadable"] == []


def test_several_bad_files_are_all_named_rather_than_the_first(door):
    """`load_repo` stopped at the first one and raised, so a repository with three
    broken files told you about one, and told you about the next only after you
    had fixed it."""
    path, _ = door
    commit_directly(
        path,
        SEED | {
            "tasks/task-d00001.md": "no frontmatter here\n",
            "cycles/0039.md": "---\ncycle: 39\nstarts_on: [oops\n---\n",
            "config/people.yaml": "known_people: [ann, bo\n",
        },
        "three files nobody can read",
    )

    with TestClient(create_app(path, auth="dev")) as client:
        named = " ".join(unreadable_in(client.get("/").text))

        for where in ("tasks/task-d00001.md", "cycles/0039.md", "config/people.yaml"):
            assert where in named, named


# --------------------------------------------------------------------------- #
# The write path over the same file
# --------------------------------------------------------------------------- #


def test_saving_a_file_that_will_not_parse_is_a_refusal_naming_it(door):
    """`patch_text` loads the frontmatter it is editing, so a save against a file
    whose YAML never closes raised a ruamel ParserError under the router — a 500
    with a `text/plain` body, which is the one answer the editor cannot read back
    to say what happened."""
    from test_web import SECRET, head

    from openproj.auth import User, sign_session

    path, _ = door
    commit_directly(path, SEED | {PATH: "---\ntitle: [unclosed\n---\n\nBody\n"}, "broken")

    with TestClient(create_app(path, auth="dev", secret=SECRET)) as client:
        ann = sign_session(User(login="ann", member=True), SECRET)
        client.cookies.set("__Host-openproj_session", ann)
        answer = client.patch(
            f"/api/record/{TASK}",
            json={"base_commit": head(client), "fields": {"priority": "high"}},
        )

        assert answer.status_code == 422, answer.text
        assert PATH in answer.json()["detail"]


def test_a_file_below_the_directory_does_not_claim_the_id_above_it(door):
    """The write path walked `tasks/` recursively too, and it matched on a stem.

    A directory somebody made to keep notes in — `tasks/task-c00001--notes/` —
    puts a file whose stem is `task-c00001--notes/notes`, which starts with
    `task-c00001--`, so `_path_for` found two files claiming one id and answered
    409: the record itself became unsaveable, from a page that said nothing about
    why, because of a file no read path had ever loaded. The read side and the
    write side have to agree about which file is the record.
    """
    from test_web import SECRET, head

    from openproj.auth import User, sign_session

    path, _ = door
    orphan = f"tasks/{TASK}--notes/notes.md"
    commit_directly(path, SEED | {orphan: "---\ntitle: Notes\n---\n"}, "a folder of notes")

    with TestClient(create_app(path, auth="dev", secret=SECRET)) as client:
        client.cookies.set(
            "__Host-openproj_session", sign_session(User(login="ann", member=True), SECRET)
        )
        answer = client.patch(
            f"/api/record/{TASK}",
            json={"base_commit": head(client), "fields": {"priority": "high"}},
        )

        assert answer.status_code == 200, answer.text
        # And the file is still named, because it is still a file nothing reads.
        assert any(orphan in line for line in unreadable_in(client.get("/").text))


# --------------------------------------------------------------------------- #
# The diagnostic tools, which is where you go once a page has said something
# --------------------------------------------------------------------------- #


BROKEN_ON_DISK = {
    "config/defaults.yaml": "schema_version: 2\n",
    "tasks/task-a00001.md": (
        "---\nid: task-a00001\nkind: task\ntitle: An ordinary task\nstatus: ready\n"
        "owner: ann\nreviewers: [bo]\nperson_weeks: 1\n---\n\nBody.\n"
    ),
    "tasks/task-a00002.md": "Just some notes I pasted into the folder.\n",
    "cycles/0039.md": "---\ncycle: 39\nstarts_on: [oops\n---\n",
}


@pytest.fixture
def on_disk(tmp_path: Path) -> Path:
    for relative, text in BROKEN_ON_DISK.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_check_names_every_file_it_could_not_read_and_fails(on_disk: Path, capsys):
    """It raised. A traceback instead of a report, out of a command whose only job
    is to report, and it stopped at the first bad file — so a repository with
    three of them told you about one, and told you about the next only once you
    had fixed that one and run it again.

    Counted as blockers too. "0 blockers, 0 warnings" over a plan that is missing
    two of its four files is the same wrong answer this command gave once before,
    on the plan that answered 500 on every route.
    """
    from openproj.cli import main

    code = main(["check", str(on_disk)])
    out = capsys.readouterr().out

    assert code == 1
    assert "tasks/task-a00002.md" in out
    assert "cycles/0039.md" in out
    assert "\n2 blockers, " in out, out


def test_check_names_a_record_filed_one_directory_too_deep(on_disk: Path, capsys):
    """The half of this a page cannot show for you.

    `load_repo` globbed each plan directory one level, so a `people/team/ann.md`
    was not merely skipped — it was never looked at, and `check` said "0
    blockers" about a file the served page was drawing as somebody's icon. That
    is the diagnostic tool agreeing that everything is fine while the two halves
    of the application disagree about which record is which, which is the exact
    shape of the round that ended with `check` reporting nothing on a plan that
    500ed every route. It walks the whole directory now and names what is down
    there.
    """
    from openproj.cli import main

    (on_disk / "people" / "team").mkdir(parents=True)
    (on_disk / "people" / "team" / "ann.md").write_text(
        "---\nicon: turtle\n---\n", encoding="utf-8"
    )

    code = main(["check", str(on_disk)])
    out = capsys.readouterr().out

    assert code == 1
    assert "people/team/ann.md" in out
    # And what to do about it, which is the half of a message that gets acted on.
    assert "move it up into people/" in out
    assert "\n3 blockers, " in out, out


def test_check_still_reports_the_records_that_did_read(on_disk: Path, capsys):
    """The file it could not read must not cost it the ones it could: `check` is
    what CI runs, and a command that stops at the first bad file hides every
    problem behind it."""
    from openproj.cli import main

    (on_disk / "tasks/task-a00003.md").write_text(
        "---\nid: task-a00003\nkind: task\ntitle: Done with nothing to show\n"
        "status: done\n---\n",
        encoding="utf-8",
    )

    main(["check", str(on_disk)])

    assert "task-a00003" in capsys.readouterr().out


def test_render_writes_every_page_and_says_what_it_left_out(on_disk: Path, tmp_path: Path, capsys):
    """`openproj render` wrote no files at all on a plan like this. Both of the
    tools you would reach for to find out what was wrong were dead."""
    from openproj.cli import main

    out_dir = tmp_path / "site"
    assert main(["render", str(on_disk), str(out_dir)]) == 0
    said = capsys.readouterr().out

    assert (out_dir / "index.html").is_file()
    assert "tasks/task-a00002.md" in said
    # And the exported page carries it too — a static build has no server to ask.
    assert any(
        "tasks/task-a00002.md" in line
        for line in unreadable_in((out_dir / "index.html").read_text(encoding="utf-8"))
    )


def test_schedule_still_prints_a_schedule(on_disk: Path, capsys):
    from openproj.cli import main

    assert main(["schedule", str(on_disk), "--json"]) == 0
    printed = capsys.readouterr()

    assert "task-a00001" in printed.out
    # The warning goes to stderr so `--json` stays something a script can pipe.
    assert "cycles/0039.md" in printed.err


# --------------------------------------------------------------------------- #
# No page can forget, and the list is not written down by hand
# --------------------------------------------------------------------------- #


def test_every_page_the_renderer_can_draw_carries_the_banner(on_disk: Path):
    """Derived from `render.py`'s own module namespace rather than listed here.

    Eight entry points call `_page`, and a list of them written out in a test is
    a list that goes stale on the commit that adds the ninth — which is the same
    way the nav mark was forgotten on two routes and the marker corpus went nine
    strings short. The one page that forgets this banner is a page that silently
    draws a plan short, which is the whole failure.
    """
    import inspect
    from datetime import date

    from openproj import render
    from openproj.index import build_index
    from openproj.model import load_repo

    records, config, unreadable = load_repo(on_disk)
    index = build_index(records, config, date(2026, 8, 17), unreadable)
    assert len(unreadable) == 2, "the corpus stopped being broken, so this proves nothing"

    drawn = 0
    for name, entry in sorted(vars(render).items()):
        if not name.startswith("render_") or name == "render_static":
            continue
        wanted = inspect.signature(entry).parameters
        arguments = {"index": index} if "index" in wanted else {}
        if "kind" in wanted:
            arguments |= {"kind": "task", "base_commit": "deadbee"}
        if "number" in wanted:
            arguments |= {"number": 37}
        # The slide editor is of ONE record and cannot be drawn without saying
        # which — the first entry point here to need an argument the corpus has
        # to supply. Taken from the index rather than written down, for the same
        # reason this loop reads `render.py`'s namespace rather than listing it:
        # a fixture id typed in here is an id that goes stale the day the corpus
        # is regenerated.
        if "record_id" in wanted:
            arguments |= {"record_id": next(iter(index.records))}
        named = unreadable_in(entry(**arguments))
        assert any("tasks/task-a00002.md" in line for line in named), f"{name} said {named}"
        drawn += 1
    assert drawn >= 7, f"only {drawn} entry points were exercised, so this proves little"


def test_the_banner_says_how_many_and_why_rather_than_only_that(on_disk: Path):
    """A path with no reason beside it sends somebody to a file to work out what
    is wrong with it, which is the thing the parser already knows."""
    from datetime import date

    from openproj.index import build_index
    from openproj.model import load_repo
    from openproj.render import ROUTES, render_table

    records, config, unreadable = load_repo(on_disk)
    page = render_table(build_index(records, config, date(2026, 8, 17), unreadable), ROUTES)

    named = sorted(unreadable_in(page))
    assert named[0].startswith("cycles/0039.md — ")
    # The scanner knows where it gave up, and that line is the whole reason a
    # YAML error is actionable — it is also the part `str(error)` buries under
    # a caret drawing that would take four lines of the banner.
    assert re.search(r", line \d+$", named[0]), named[0]
    assert named[1].startswith("tasks/task-a00002.md — no YAML frontmatter")
    assert "2 files in the plan are not records" in page


def test_one_file_is_said_in_the_singular():
    """`1 files are not records` is the copy that tells a reader nobody looked."""
    from datetime import date

    from openproj.index import build_index
    from openproj.model import Config, Unreadable
    from openproj.render import ROUTES, render_table

    index = build_index([], Config(), date(2026, 8, 17), [Unreadable(path="tasks/x.md", why="no")])

    assert "One file in the plan is not a record" in render_table(index, ROUTES)


# --------------------------------------------------------------------------- #
# The banner is text somebody else wrote, on every page, for every reader
# --------------------------------------------------------------------------- #

# The same payload the injection census uses: a quote to end whatever attribute
# it lands in, a `>` to end the tag, an `<img onerror>` to prove an element was
# created, and a `</script>` with a second image to prove a script block was
# closed early.
PAYLOAD = '" ><img src=x onerror=alert(1)> & </script><img src=y onerror=alert(2)>'


def test_a_file_name_nobody_should_have_used_is_still_only_text(door):
    """Both halves of a banner line are somebody else's writing.

    The path is a name in the git tree, and a person with a terminal can commit
    a file called anything a filesystem will hold — `git` will happily carry
    `tasks/" ><img src=x onerror=alert(1)>.md`. The reason beside it quotes the
    file's own contents, because that is what a YAML scanner and a pydantic
    validator both say. So this banner puts two attacker-chosen strings onto
    every page in the app, for every reader, including anonymous ones — which is
    a wider audience than any field the injection census covers, and it did not
    exist when that census was written.

    Asked of a parser, not of a substring: `&lt;img&gt;` in a filename and
    `<img>` in the markup are the same characters and completely different
    things, and telling them apart is the whole question.
    """
    from test_injection import assert_clean

    path, _ = door
    commit_directly(
        path,
        SEED | {f"tasks/{PAYLOAD}.md": "no frontmatter, and a name nobody should have used\n"},
        "a file name from the other side",
    )

    with TestClient(create_app(path, auth="dev")) as client:
        for route in ROUTES:
            if route in ("/api/index.json", "/healthz"):
                continue
            page = client.get(route).text
            assert_clean(page, f"{route} with a hostile file name")
            assert any(PAYLOAD in line for line in unreadable_in(page)), (
                f"{route} did not name the file at all: {unreadable_in(page)}"
            )


def test_a_reason_quoting_the_file_is_still_only_text(door):
    """The other half of the line, and it is reachable.

    `why_it_will_not_read` joins a ValidationError's `loc`, and for a map that
    `loc` is the key somebody wrote. A cycle's `availability` is keyed by login,
    so a roster naming `"<img src=x onerror=alert(1)>": "half"` puts that key
    verbatim into the sentence this banner prints on every page — including to
    anonymous readers, which is a wider audience than any field the injection
    census covers.

    Written against a message that demonstrably carries the value: most pydantic
    messages do not quote what they rejected, and a test whose payload never
    reaches the string it is about proves nothing about escaping. This one is
    checked both ways round — the payload has to be *in* the banner, and the
    page still has to contain no element the plan did not put there.
    """
    from test_injection import assert_clean

    path, _ = door
    commit_directly(
        path,
        SEED | {
            "cycles/0042.md":
                "---\ncycle: 42\nstarts_on: 2026-09-01\navailability:\n"
                f"  '{PAYLOAD}': half\n---\n"
        },
        "a login that would rather be markup",
    )

    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/table").text
        assert_clean(page, "the table with a hostile value in a reason")
        said = " ".join(unreadable_in(page))
        assert "cycles/0042.md" in said
        assert "img src=x" in said, f"the reason did not quote the value at all: {said}"


def test_the_banner_does_not_change_the_shape_of_a_page_it_names(tmp_path: Path):
    """The census, over the two corpora that differ only in what the text says.

    A payload that reaches the banner as markup would add elements here; a
    payload that is escaped adds none, whatever it says. This is the assertion
    that holds for the next payload rather than for this one.
    """
    from test_injection import assert_same_shape

    # A repository each. The store takes an exclusive flock for the life of the
    # process, so two apps over one path is a StoreLocked rather than a census.
    pages = {}
    for label, name in (("hostile", PAYLOAD), ("benign", "an ordinary note to myself")):
        path = tmp_path / f"{label}.git"
        pygit2.init_repository(str(path), bare=True, initial_head="main")
        commit_directly(path, SEED | {f"tasks/{name}.md": "no frontmatter\n"}, label)
        with TestClient(create_app(path, auth="dev")) as client:
            pages[label] = client.get("/table").text

    assert_same_shape(pages["hostile"], pages["benign"], "the table's unreadable banner")
