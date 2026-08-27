"""The favicon, and the drawings a person picks a mark from."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from markupsafe import Markup

# Three staggered bars: a schedule, which is what this whole application draws.
# Sized on a 16-unit grid because 16px is where a favicon is actually judged, and
# one mid teal rather than the theme's two — the tab strip is painted by the
# browser in a theme this page is not told about, so a colour that survives both
# grounds beats a colour that is right on one of them.
_ICON = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
    "<rect x='1' y='2' width='10' height='3.2' rx='1.6' fill='#27899e'/>"
    "<rect x='4' y='6.4' width='11' height='3.2' rx='1.6' fill='#27899e'/>"
    "<rect x='2' y='10.8' width='7' height='3.2' rx='1.6' fill='#27899e'/>"
    "</svg>"
)


@lru_cache(maxsize=1)
def _icon_uri() -> str:
    """The mark as a data: URI, so the tab has an icon and nothing is fetched.

    Without a `<link rel="icon">` a browser goes and asks for `/favicon.ico` on
    its own, which is a 404 in the log of every page load — and over `file://`,
    where the static export lives, it is a console error against a path that
    could never exist. An inline SVG answers the question before it is asked.

    A served route would fix the first and not the second, and would be one more
    thing the export has to carry as a separate file. Percent-encoded rather than
    base64 so the source above stays a picture somebody can read and edit.
    """
    return "data:image/svg+xml," + quote(_ICON, safe="")


# A person's own mark, drawn beside their name on the People page and nowhere
# else. Inline SVG rather than emoji — which is the same answer STATUS_GLYPH
# above gives, reached by a different argument, because the argument that
# decided the status marks does not apply here.
#
# A status mark is text because it sits inside a 14px timeline bar and has to
# arrive in the bar's own ink: an emoji is drawn by the platform's colour font,
# so it ignores `currentColor` and lands at a different weight on every machine.
# An avatar wants none of that. It is 20px of its own, it is allowed its own
# colour, and being recognisable matters more than matching the ink — so on the
# trade-off that settled the status marks, emoji would win here.
#
# What rules them out is the other promise this codebase makes. Everything a
# page needs is inside the page: the typeface is a `data:` URI, every library is
# inlined, and `test_no_page_reaches_the_network` is what keeps it so — because
# `openproj render` writes a plan that has to be readable off a memory stick
# with no network and nothing installed. An emoji is the one mark that is not in
# the file. It is resolved by whatever colour-emoji font the reader happens to
# have, which on an ordinary Linux workstation is none at all, and a login whose
# icon is a tofu box is worse than a login with no icon: it looks like the tool
# is broken rather than like nobody has chosen. The same file opened on three
# machines would draw three different foxes, and the one thing on this page that
# is a person's own choice is the last thing that should be a property of their
# neighbour's font cache.
#
# So: paths, in the page, in `currentColor`. About 200 bytes each, they follow
# the theme, they scale, and the drawing in the file IS the drawing on screen.
# Stroked outlines at the interface's own weight rather than filled silhouettes,
# and every feature is a whole shape — a head, two ears, two eyes — because at
# 20px a whisker is not a line, it is a grey smudge.
#
# Twenty-four of them, which is a team's worth with room to choose rather than
# one each. The count is not the constraint and never was: being told apart at
# 20px is, and that is what decides how many there can be. Every candidate was
# drawn, rendered at 20px beside the whole set, and looked at, because a shape
# that reads in the source is not evidence about pixels. Seven did not survive
# that and are deliberately absent — a WHALE and a SNAKE, which at that size are
# the fish and the wave this set already has; a SNAIL and a PENGUIN, whose second
# outline inside the first closed into a blot; a BEE, whose stripes did the same;
# a RAINBOW, three concentric arcs that resolve into one thick arc; and a DOG,
# which was a third round face after the cat and the bear. They are named here
# because a shape is rejected for what it collides with rather than for being
# badly drawn, and the next person to add one needs the collisions more than they
# need the survivors.
#
# Three groups, in the order the picker is read: the sky, then the world, then
# the creatures — and inside the creatures, the ones that walk before the ones
# that swim. A list ordered by nothing is a list a reader has to search rather
# than scan. What is stored is the NAME, so these can be redrawn, and this order
# rearranged, without touching anybody's choice — see `model.Person`.
_ICON_ART = {
    "sun": (
        '<circle cx="12" cy="12" r="4.3"/>'
        '<path d="M12 2.4v2.6M12 19v2.6M2.4 12h2.6M19 12h2.6'
        'M5.3 5.3 7.2 7.2M16.8 16.8l1.9 1.9M18.7 5.3 16.8 7.2M7.2 16.8l-1.9 1.9"/>'
    ),
    "moon": '<path d="M20 13.4A8.8 8.8 0 1 1 10.6 4 7 7 0 0 0 20 13.4Z"/>',
    "star": (
        '<path d="M12 3.3 14.2 9.2 20.6 9.5 15.6 13.5 17.3 19.6 12 16.1'
        ' 6.7 19.6 8.4 13.5 3.4 9.5 9.8 9.2Z"/>'
    ),
    "cloud": (
        '<path d="M7.4 18.6h9.8a4.2 4.2 0 0 0 .4-8 5.7 5.7 0 0 0-10.8-1.3a4.8 4.8 0 0 0 .6 9.3Z"/>'
    ),
    "bolt": '<path d="M13.8 2.6 5.8 13.8h4.8l-.8 7.6 8.4-11.4h-5Z"/>',
    # Six spokes and a chevron at each tip, and nothing along them. The version
    # with branches half way out was a blot at 20px: eighteen strokes inside 20
    # pixels is a grey disc. The sun is the shape it has to stay clear of and
    # does — the sun is a solid centre with detached rays, this is one open
    # asterisk with a hole in the middle.
    "snowflake": (
        '<path d="M12 2.4v19.2M3.7 7.2l16.6 9.6M20.3 7.2 3.7 16.8"/>'
        '<path d="M8.8 4.8 12 8l3.2-3.2M8.8 19.2 12 16l3.2 3.2"/>'
    ),
    # Upright and unmarked, which is the whole of what separates it from the leaf
    # below: that one is tilted and carries a midrib, and a drop that leaned would
    # be the same lens.
    "drop": (
        '<path d="M12 2.6c4.4 5.6 6.6 8.6 6.6 11.2a6.6 6.6 0 0 1-13.2 0c0-2.6 2.2-5.6 6.6-11.2Z"/>'
    ),
    # The ring passes behind the body as two arcs that stop at its edge, rather
    # than as one ellipse crossing it. An ellipse drawn over the disc lays two
    # chords across the planet, and at 20px a circle with a line through it is a
    # circle with a line through it.
    "planet": (
        '<circle cx="12" cy="12" r="5.6"/>'
        '<path d="M7.1 14.7c-3.5 1.6-6.2 2-6.8.7-.6-1.3 1.2-3.5 4.4-5.5'
        'M16.9 9.3c3.5-1.6 6.2-2 6.8-.7.6 1.3-1.2 3.5-4.4 5.5"/>'
    ),
    "mountain": '<path d="M2.6 19.4 9.4 7.6l4 6.9 2.6-4.3 5.4 9.2Z"/>',
    # Tilted, and fat enough to have two sides. Drawn upright and narrow it was a
    # sliver with a line down it — at 20px indistinguishable from an eye, and the
    # midrib was the whole of what made it a leaf rather than a lens.
    "leaf": (
        '<path d="M4.6 19.4a11.5 11.5 0 0 1 14.8-14.8 11.5 11.5 0 0 1-14.8 14.8Z"/>'
        '<path d="M2.8 21.2 18 6"/>'
    ),
    # The trunk is the whole of what tells this from the mountain at 20px, so it
    # is drawn long enough to see. A bare triangle is a peak, and a triangle with
    # a two-pixel stub under it is a peak somebody smudged.
    "tree": '<path d="M12 2.8 4.4 16.4h15.2Z"/><path d="M12 16.4v4.6"/>',
    # A tulip on a stem, not a rosette. Five petals round a centre is the same
    # radial blob as the sun at this size — and the sun has the better claim to
    # it — so the flower is the shape a flower has from the side instead.
    "flower": (
        '<path d="M6.2 8.2c0 4.2 2.6 7 5.8 7s5.8-2.8 5.8-7c0 0-2.2 1.8-2.9 1.8'
        'S12 5.8 12 5.8s-2.2 4.2-2.9 4.2S6.2 8.2 6.2 8.2Z"/>'
        '<path d="M12 15.2v6.2"/>'
        '<path d="M12 18.4c-1.8-2.2-4-2.4-5.2-1.6-.2 2.4 2.6 3.6 5.2 1.6Z"/>'
    ),
    # Two lines and not three: a third crest closes the gaps between them into a
    # hatched band, and two is already enough to say water rather than a squiggle.
    "wave": (
        '<path d="M2.4 9.8q2.4-3.2 4.8 0t4.8 0 4.8 0 4.8 0"/>'
        '<path d="M2.4 16.2q2.4-3.2 4.8 0t4.8 0 4.8 0 4.8 0"/>'
    ),
    "cat": (
        # One outline for the head and both ears, so no chord is drawn across the
        # face: the arc stops where each ear starts and picks up where it ends.
        '<path d="M8.9 8.8A6.2 6.2 0 0 1 15.1 8.8L19.4 4.8 17.8 12.1'
        'A6.2 6.2 0 1 1 6.2 12.1L4.6 4.8Z"/>'
        '<circle cx="9.8" cy="14" r=".95" fill="currentColor" stroke="none"/>'
        '<circle cx="14.2" cy="14" r=".95" fill="currentColor" stroke="none"/>'
    ),
    "fox": (
        '<path d="M12 20.6 4.4 12.4 3.4 4.6 8.6 7.4h6.8l5.2-2.8-1 7.8Z"/>'
        '<circle cx="8.8" cy="11.9" r=".95" fill="currentColor" stroke="none"/>'
        '<circle cx="15.2" cy="11.9" r=".95" fill="currentColor" stroke="none"/>'
    ),
    "owl": (
        '<path d="M12 3.6c-4.2 0-7 3.2-7 7.6 0 5.4 3.2 9.2 7 9.2s7-3.8 7-9.2'
        'c0-4.4-2.8-7.6-7-7.6Z"/>'
        '<path d="M8.8 4.8 7.2 2.4M15.2 4.8 16.8 2.4"/>'
        '<circle cx="9.5" cy="10.6" r="2.1"/><circle cx="14.5" cy="10.6" r="2.1"/>'
        '<circle cx="9.5" cy="10.6" r=".8" fill="currentColor" stroke="none"/>'
        '<circle cx="14.5" cy="10.6" r=".8" fill="currentColor" stroke="none"/>'
        '<path d="M12 12.4 10.9 14.3 13.1 14.3Z"/>'
    ),
    "rabbit": (
        # The ears are open at the root rather than closed shapes: a closed ear
        # draws its base across the top of the head, and two lines through the
        # face is what a rabbit at 20px turns into.
        '<circle cx="12" cy="16.2" r="4.9"/>'
        '<path d="M9.3 12.6Q6 6.4 8.4 2.8 11.6 5.6 11.4 11.5"/>'
        '<path d="M14.7 12.6Q18 6.4 15.6 2.8 12.4 5.6 12.6 11.5"/>'
        '<circle cx="10.2" cy="15.7" r=".85" fill="currentColor" stroke="none"/>'
        '<circle cx="13.8" cy="15.7" r=".85" fill="currentColor" stroke="none"/>'
    ),
    # Round ears standing outside the head, and a snout inside it. The cat's ears
    # are points on the head's own outline; these break it, and the snout is the
    # second difference — with neither of them this is the cat at 20px, which is
    # what the first attempt was.
    "bear": (
        '<circle cx="6.1" cy="7.5" r="2.7"/><circle cx="17.9" cy="7.5" r="2.7"/>'
        '<circle cx="12" cy="13.6" r="6.5"/>'
        '<circle cx="9.6" cy="12.2" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="14.4" cy="12.2" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="12" cy="16.4" r="1.9"/>'
    ),
    # Head and body are two circles that touch rather than one silhouette. Drawn
    # as a single outline a small bird is an egg with a beak on it; the notch
    # where the two circles meet is the neck, and it is the only thing at this
    # size that says which end is the front.
    "bird": (
        '<circle cx="14.8" cy="8.2" r="3.4"/>'
        '<path d="M18 7.2 21.8 8.4 18 9.8Z"/>'
        '<circle cx="15.2" cy="7.4" r=".85" fill="currentColor" stroke="none"/>'
        '<circle cx="10.4" cy="15.6" r="5.6"/>'
        '<path d="M5.8 19 1.8 21.8 2.4 17Z"/>'
    ),
    # One closed path per side, each carrying both of that side's wings, so the
    # body is the seam where the two meet rather than a third shape drawn down
    # the middle. Four separate wings put four strokes through the centre, and at
    # 20px the middle filled in.
    "butterfly": (
        '<path d="M12 8.2C8.4 3.6 2.6 4.2 2.6 8.6c0 2.3 1.9 3.5 4.4 3.5'
        '-2.5.6-4.4 2.1-4.4 4.4 0 3.7 5.6 4.4 9.4-.3Z"/>'
        '<path d="M12 8.2c3.6-4.6 9.4-4 9.4.4 0 2.3-1.9 3.5-4.4 3.5'
        '2.5.6 4.4 2.1 4.4 4.4 0 3.7-5.6 4.4-9.4-.3Z"/>'
        '<path d="M12 8.2 9.8 4.2M12 8.2l2.2-4"/>'
    ),
    # The eyes sit on top of the head and break its outline, which is the whole
    # of the difference from the owl — whose eyes are two rings inside a body
    # that closes over them.
    "frog": (
        '<circle cx="8.4" cy="7.6" r="2.6"/><circle cx="15.6" cy="7.6" r="2.6"/>'
        '<circle cx="8.4" cy="7.6" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="15.6" cy="7.6" r=".9" fill="currentColor" stroke="none"/>'
        '<path d="M4.4 13.8c0-3 3.4-5.2 7.6-5.2s7.6 2.2 7.6 5.2c0 3.4-3.4 6.2-7.6 6.2'
        's-7.6-2.8-7.6-6.2Z"/>'
        '<path d="M8.6 15.6q3.4 2.4 6.8 0"/>'
    ),
    "fish": (
        '<path d="M4.4 12a9 9 0 0 1 13.6 0 9 9 0 0 1-13.6 0Z"/>'
        '<path d="M18 12 22.4 8.6 22.4 15.4Z"/>'
        '<circle cx="7.9" cy="11.1" r=".9" fill="currentColor" stroke="none"/>'
    ),
    # Claws and eye stalks, both crossing the body's outline. A crab drawn as a
    # shell with legs under it is a face at 20px — the things that stick out are
    # what keep it out of the cat, fox, bear, frog corner of this set.
    "crab": (
        '<path d="M4.8 14.6a7.2 7.2 0 0 1 14.4 0 7.2 7.2 0 0 1-14.4 0Z"/>'
        '<path d="M9.4 9.2V7.2M14.6 9.2V7.2"/>'
        '<circle cx="9.4" cy="6" r="1" fill="currentColor" stroke="none"/>'
        '<circle cx="14.6" cy="6" r="1" fill="currentColor" stroke="none"/>'
        '<path d="M4.9 12.4 2 10.4a2 2 0 1 1 2.8-1.6"/>'
        '<path d="M19.1 12.4 22 10.4a2 2 0 1 0-2.8-1.6"/>'
        '<path d="M6.6 18.6 4.4 21M17.4 18.6l2.2 2.4"/>'
    ),
    "turtle": (
        '<path d="M4.6 15.6a7.4 7.4 0 0 1 14.8 0Z"/>'
        '<circle cx="21" cy="13.6" r="1.7"/>'
        '<path d="M7.6 15.6v2.4M12 15.6v2.6M16.4 15.6v2.4M4.6 15.2 2.4 16.4"/>'
    ),
    # A head in profile, because a whole unicorn at 20px is a horse-shaped smudge
    # with a spike on it. The horn is the entire signal — it is drawn as its own
    # shape rising clear of the skull rather than as a bump on the outline, since
    # a point that shares an edge with the head reads as an ear at this size, and
    # the ear beside it is what it would then be confused with.
    "unicorn": (
        '<path d="M3.4 16.6C3.4 12.2 6.8 8.8 11 8.5L13.2 8.3'
        'C14.6 12.4 15.2 16.7 15.4 21.2H10.2C9.8 18.4 7.2 16.8 3.4 16.6Z"/>'
        '<path d="M11.4 8.1 10.4 1.8 13.4 7.7"/>'
        '<path d="M14.2 8.2 15.4 6.3 16.1 8.7"/>'
        '<path d="M16.6 10.2Q19.6 12.6 18 15.1Q20.3 17.8 18.8 21.2"/>'
        '<circle cx="9.6" cy="12.9" r=".85" fill="currentColor" stroke="none"/>'
    ),
}

# The vocabulary, and the only thing that decides it. `web.py` refuses an icon
# this map does not hold, the picker offers exactly these, and the stored value
# is the key — so adding one is a line here and nothing anywhere else.
ICONS = tuple(_ICON_ART)

# 24 units square and drawn in the current ink, so an icon is the size of the
# text beside it and takes the theme with it. `aria-hidden`, because the name it
# sits next to is the person: a screen reader announcing "fox, jcanton" would be
# reading out a decoration as though it were an identity.
_ICON_SVG = (
    '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true" focusable="false">{}</svg>'
)


def icon_svg(name: str) -> Markup:
    """The drawing for a stored icon name, or nothing at all.

    Nothing, and not a placeholder, for a name this version does not draw: an
    icon is a decoration beside a login that is already on screen, so a stored
    `dragon` costs the drawing and nothing else. That is the same bargain
    `_status_class` makes with a status nobody recognises, one rung down — there
    is no rule to fold this onto, because there is nothing underneath a mark.
    """
    art = _ICON_ART.get(name)
    return Markup(_ICON_SVG).format(Markup(art)) if art else Markup("")
