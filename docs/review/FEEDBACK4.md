# Round eight — the nav says where you are, and the heading stops repeating it

> "currently navigation and page title could do better: remove title and highlight
> with box / bold / color the navigation corresponding to the current page!"

Right on both halves. The nav currently marks the current page by *not* underlining
it, which is the weakest signal available and is invisible next to five underlined
siblings. And a page whose whole heading is the word already sitting in the nav is
a row of vertical space spent saying nothing new — which is what the graph page was
complaining about two notes ago.

There is one constraint, and it points at a better version of the change rather
than against it.

## The heading cannot simply be deleted

Round six's accessibility pass added an `<h1>` to every page, and
`tests/test_render.py:2345` asserts one per page, for the reason it states: a page
with no `<h1>` cannot be announced by name and cannot be navigated to by heading.
Deleting them would undo a fix this branch made two rounds ago and break the test
that protects it.

So the heading stays in the document and leaves the screen. `.sr-only` already
exists in the shell (`render.py:1103`) and is already used for exactly this kind of
thing, so this is a class, not a mechanism.

## The distinction that decides which headings go

Not every `<h1>` on this app is a page label. Two kinds:

- **A heading that repeats the nav** — "Table", "Graph", "Timeline", "Cycles",
  "People". These say nothing the highlighted nav item will not say better. They
  become `.sr-only`.
- **A heading that names the thing you are looking at** — the entity title on the
  detail page, "Cycle 37" on the cycle page. These are content, not chrome. They
  stay visible, and they are the reason the rule is not "remove the h1".

Decide "New entity" deliberately and say which it is; it is a page label by
wording, but it is also the only thing on that page that says what the form will
make.

## The highlight

`aria-current="page"` on the current item first — that is the semantic version of
the highlight, it is what a screen reader announces, and it is what the visible
treatment should be styled from, so the two cannot disagree.

Visually: weight, colour and a box. All three, deliberately, because colour alone
is not a signal we accept anywhere else in this app and a nav is the one component
every page carries. Use the existing tokens; the accent already means "this is
interactive and this is ours".

Keep it quiet. The nav is 13px chrome at the top of a dense tool, not a tab bar —
a filled chip in `--accent` across the top of every page would shout. A subtle
ground, the accent, and a heavier weight is enough to be unmissable at a glance
without being the loudest thing on a page full of data.

## Check afterwards

- Every page still has exactly one `<h1>`; the test that asserts it still passes,
  and gains a sibling asserting the label-only ones are `.sr-only` while the
  content ones are not.
- The current item is marked on all seven routes, including `/detail/<id>` and
  `/cycle/<n>`, which are not the same href as the nav link that leads to them.
- The static export marks the right item too — it has no server to ask.
- The row of space actually comes back: measure the top of the table, the graph
  canvas and the timeline before and after, and say how much.
