# Round five — the seventh site, and two ways to break the plan permanently

Round four closed all sixteen named defects and the audit confirmed them on real
pages. Then it found the site the sweep missed, and it is worse than the six.

---

## A7 — BLOCKER. Page assembly splices raw JSON into finished markup.

Every page is built by rendering a template and **then** running `str.replace` over
the result:

- `render.py:6103` — `PAYLOAD_JSON`, `ENTITY_HREF`
- `render.py:6125, 6127` — `ELEMENTS_JSON`, then `re.sub` over `@@name@@`
- `render.py:6134, 6171` — `BARS_JSON`
- `render.py:5708` — `HELD_JSON`
- `render.py:5836` — `ROSTER_JSON`

By the time those run, the text already holds titles, owners, tags and logins
somebody typed. So a **value that equals a marker** is substituted, and `_json()`
escapes `<`, `>` and `&` but not `"`, so what lands there carries raw quotes into
whatever attribute it lands in.

Proven end to end through the API, not by hand-editing a file. One request:

    PATCH /api/entity/pitch-0a0001
    {"fields": {"title": "BARS_JSON", "owner": "x onmouseover=alert(1) y"}}

returns 200, commits, and `GET /timeline` then parses with a live
`<a onmouseover="alert(1)">` on the bar links, for every reader. Neither field
contains a single character any escaper would touch.

The same shape, elsewhere: `tags: ["PAYLOAD_JSON"]` puts a handler in the table's
facet bar; a roster login of `HELD_JSON` puts six on the cycle page; and a title of
`@@cytoscape.min.js@@` re-inlines the whole library into the graph's data block —
796 KB becomes 1.5–3.8 MB and `json.loads` on `<script id="elements">` raises, so
the graph loads with no plan at all. The static export takes the same path.

**The fix is to stop doing it, not to escape harder.** Post-render substitution
over text that already contains user data is the defect; any escaping scheme layered
on top of it is a second thing to get right. Give each JSON block a template
variable rendered through Jinja's own escaping (or `Markup` where the value is
genuinely trusted markup), and do the vendored-library inlining before user data is
anywhere near the string. When you are done, `str.replace` and `re.sub` must not
appear anywhere in the page-assembly path — grep for them and show the grep in your
report.

While you are there: `_json()` should escape the double quote too. Belt and braces
is fine here; it is one character and the cost is nothing.

**The test that would have caught it.** The branch's injection test compares a
hostile page against a benign one, and neither corpus contains the marker words —
which is precisely why it saw nothing. Add every marker string (`PAYLOAD_JSON`,
`ELEMENTS_JSON`, `BARS_JSON`, `HELD_JSON`, `ROSTER_JSON`, `ENTITY_HREF`,
`@@cytoscape.min.js@@`, `@@dagre.min.js@@`, `@@cytoscape-dagre.js@@`) to the hostile
corpus as a title, a tag, an owner and a login, and assert the rendered pages are
structurally identical to the benign ones and that every JSON block still parses.
Derive the marker list from the code so a new marker cannot be added without the
test knowing about it.

---

## B — HIGH. `PATCH /api/entity` commits values the model cannot read back.

`web.py:477-503` writes without the parse-before-write round trip that the cycle
route was just given at `web.py:536-541` — whose comment describes exactly this bug
on the endpoint beside it:

> a roster that fails to load would take every date on every page with it, and the
> file would already be in git

`_reject_bad_types` guards numbers, lists and one bool. Every one of these returns
200 and commits, after which `GET /`, `GET /detail/<id>` and `GET /api/index.json`
all answer 500, for everybody, permanently:

`owner: {a:1}` · `owner: [a,b]` · `title: {a:1}` · `title: 5` · `assigned_on: ""` ·
`assigned_on: "six"` · `assigned_on: 7` · `tags: [null]` · `tags: [{a:1}]` ·
`parent: 3` · `created_schema_version: "x"`

It is a commit on a protected main, so it cannot be force-pushed away, and the only
repair is a second crafted PATCH against the poisoning commit's sha — which the
500ing pages will not give you.

Not reachable through the shipped UI. That is not a mitigation: it needs one
deliberate request from any signed-in member.

Give the entity route the same parse-before-write refusal, with a 422 that names the
field and says what it could not read. Test every one of the eleven cases.

---

## C — LOW. `_after_markdown` re-links a PR reference already inside a link.

`render.py:621` runs `_PR.sub` over markdown-it's finished HTML with no regard for
context. A body containing `[a pr link](https://github.com/org/repo#12)` renders as
an anchor nested inside an `href`, which the tokeniser turns into one anchor with
junk valueless attributes. A PR reference inside a code span becomes a link too.

Not an injection — the replacement is fixed and the matched repo and number are
`[\w.-]+` — but it is broken markup on the detail page, the static export and the
preview fragment, and it affects the benign page as much as the hostile one, which
is why a hostile-versus-benign comparison could not see it.

Fix it by skipping text inside `<a>` and `<code>` — walk the tokens, or match on
text nodes rather than on the finished string.

---

## D — LOW. An entity id goes into a fetch URL without encoding.

`render.py:1741` `fetch(`/api/entity/${cell.dataset.entity}`)` and `render.py:2651`
the same in the graph. A malformed id is a reported blocker rather than a refusal,
so such an id does reach the page; one containing `#` or `?` truncates the path and
the write goes somewhere else entirely. `encodeURIComponent`.
