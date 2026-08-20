"""Colour schemes, as sixteen numbers each.

A base16 scheme is sixteen colours in a fixed order: eight steps of ground from
the background to the brightest ink, then eight hues — red, orange, yellow,
green, cyan, blue, magenta, brown. That is the whole format, and it is the reason
this file is short: a scheme is a row of sixteen hex values, and everything the
app draws is derived from those in ONE place (`_SCHEME_CSS` in `render.py`)
rather than tuned per scheme. Twenty palettes and one mapping, not twenty
palettes and twenty mappings.

The mapping is where the taste is, and it is spelled out beside the CSS: a status
is a hue, a priority is a hue, and the soft grounds a chip needs are the hue
mixed into the background with `color-mix`, which is what stops a scheme from
having to supply forty values it does not have.

Schemes come in FAMILIES of two — a light and a dark — because this app already
has a light/dark switch and taking it away to make room for a scheme picker would
be trading one control for another. The picker chooses the family; the switch
still chooses the polarity, and each family answers for both.

The data is from tinted-theming/schemes (MIT), spec 0.11, fetched 2026-08-20 and
copied here rather than vendored as files: sixteen hex values per palette is
smaller than the machinery to read a directory of YAML at startup, and a scheme
that changes upstream should be a diff somebody reads. Each palette carries the
name and author it was published under. Full attribution is in `VENDOR.md`.
"""

from __future__ import annotations

from typing import NamedTuple

# The sixteen slots, in the order the format defines them. base00..base07 are the
# ground running from background to brightest, base08..base0F the hues.
SLOTS = tuple(f"base0{c}" for c in "0123456789ABCDEF")


class Palette(NamedTuple):
    """One scheme: sixteen colours, and who to credit for them."""

    source: str          # the file it came from upstream
    name: str            # what its author called it
    author: str
    colours: str         # sixteen hex triplets, in SLOTS order, space separated

    @property
    def slots(self) -> dict[str, str]:
        """`{"base00": "#f8f8f8", ...}` — parsed here rather than stored, so the
        table above stays a table somebody can read a row of."""
        values = self.colours.split()
        if len(values) != len(SLOTS):
            raise ValueError(f"{self.source}: {len(values)} colours, expected 16")
        return {slot: f"#{value}" for slot, value in zip(SLOTS, values, strict=True)}


class Family(NamedTuple):
    """A scheme in both polarities. The picker offers the family; the light/dark
    switch chooses which of the two is on."""

    key: str             # what goes in `data-scheme`, and into localStorage
    label: str           # what the picker says
    light: Palette
    dark: Palette


FAMILIES: tuple[Family, ...] = (
    Family("default", "Base16",
           Palette("default-light", "Default Light", "Chris Kempson",
                   "f8f8f8 e8e8e8 d8d8d8 b8b8b8 585858 383838 282828 181818 "
                   "ab4642 dc9656 f7ca88 a1b56c 86c1b9 7cafc2 ba8baf a16946"),
           Palette("default-dark", "Default Dark", "Chris Kempson",
                   "181818 282828 383838 585858 b8b8b8 d8d8d8 e8e8e8 f8f8f8 "
                   "ab4642 dc9656 f7ca88 a1b56c 86c1b9 7cafc2 ba8baf a16946")),
    Family("gruvbox", "Gruvbox",
           Palette("gruvbox-light-medium", "Gruvbox light, medium", "Dawid Kurek",
                   "fbf1c7 ebdbb2 d5c4a1 bdae93 665c54 504945 3c3836 282828 "
                   "9d0006 af3a03 b57614 79740e 427b58 076678 8f3f71 d65d0e"),
           Palette("gruvbox-dark-medium", "Gruvbox dark, medium", "Dawid Kurek",
                   "282828 3c3836 504945 665c54 bdae93 d5c4a1 ebdbb2 fbf1c7 "
                   "fb4934 fe8019 fabd2f b8bb26 8ec07c 83a598 d3869b d65d0e")),
    Family("solarized", "Solarized",
           Palette("solarized-light", "Solarized Light", "Ethan Schoonover",
                   "fdf6e3 eee8d5 93a1a1 839496 657b83 586e75 073642 002b36 "
                   "dc322f cb4b16 b58900 859900 2aa198 268bd2 6c71c4 d33682"),
           Palette("solarized-dark", "Solarized Dark", "Ethan Schoonover",
                   "002b36 073642 586e75 657b83 839496 93a1a1 eee8d5 fdf6e3 "
                   "dc322f cb4b16 b58900 859900 2aa198 268bd2 6c71c4 d33682")),
    Family("tomorrow", "Tomorrow",
           Palette("tomorrow", "Tomorrow", "Chris Kempson",
                   "ffffff e0e0e0 c5c8c6 b4b7b4 969896 373b41 282a2e 1d1f21 "
                   "c82829 f5871f eab700 718c00 3e999f 4271ae 8959a8 a3685a"),
           Palette("tomorrow-night", "Tomorrow Night", "Chris Kempson",
                   "1d1f21 282a2e 373b41 969896 b4b7b4 c5c8c6 e0e0e0 ffffff "
                   "cc6666 de935f f0c674 b5bd68 8abeb7 81a2be b294bb a3685a")),
    Family("one", "One",
           Palette("one-light", "One Light", "Daniel Pfeifer",
                   "fafafa f0f0f1 e5e5e6 a0a1a7 696c77 383a42 202227 090a0b "
                   "ca1243 d75f00 c18401 50a14f 0184bc 4078f2 a626a4 986801"),
           Palette("onedark", "OneDark", "Lalit Magant",
                   "282c34 353b45 3e4451 545862 565c64 abb2bf b6bdca c8ccd4 "
                   "e06c75 d19a66 e5c07b 98c379 56b6c2 61afef c678dd be5046")),
    Family("papercolor", "PaperColor",
           Palette("papercolor-light", "PaperColor Light", "Jon Leopard",
                   "eeeeee c4c4c4 9e9e9e 858585 6b6b6b 5e5e5e 525252 444444 "
                   "d70000 d75f00 d75f00 008700 0087af 005f87 8700af af0000"),
           Palette("papercolor-dark", "PaperColor Dark", "Jon Leopard",
                   "1c1c1c 363636 424242 585858 808080 9e9e9e b8b8b8 d0d0d0 "
                   "ff5faf d7af5f ffaf00 5faf5f 00afaf 5fafd7 af87d7 af005f")),
    Family("equilibrium", "Equilibrium",
           Palette("equilibrium-light", "Equilibrium Light", "Carlo Abelli",
                   "f5f0e7 e7e2d9 d8d4cb 73777f 5a5f66 43474e 2c3138 181c22 "
                   "d02023 bf3e05 9d6f00 637200 007a72 0073b5 4e66b6 c42775"),
           Palette("equilibrium-dark", "Equilibrium Dark", "Carlo Abelli",
                   "0c1118 181c22 22262d 7b776e 949088 afaba2 cac6bd e7e2d9 "
                   "f04339 df5923 bb8801 7f8b00 00948b 008dd1 6a7fd2 e3488e")),
    Family("silk", "Silk",
           Palette("silk-light", "Silk Light", "Gabriel Fontes",
                   "e9f1ef ccd4d3 90b7b6 5c787b 4b5b5f 385156 0e3c46 d2faff "
                   "cf432e d27f46 cfad25 6ca38c 329ca2 39aac9 6e6582 865369"),
           Palette("silk-dark", "Silk Dark", "Gabriel Fontes",
                   "0e3c46 1d494e 2a5054 587073 9dc8cd c7dbdd cbf2f7 d2faff "
                   "fb6953 fcab74 fce380 73d8ad 3fb2b9 46bddd 756b8a 9b647b")),
    Family("forest", "Atelier Forest",
           Palette("atelier-forest-light", "Atelier Forest Light", "Bram de Haan",
                   "f1efee e6e2e0 a8a19f 9c9491 766e6b 68615e 2c2421 1b1918 "
                   "f22c40 df5320 c38418 7b9726 3d97b8 407ee7 6666ea c33ff3"),
           Palette("atelier-forest", "Atelier Forest", "Bram de Haan",
                   "1b1918 2c2421 68615e 766e6b 9c9491 a8a19f e6e2e0 f1efee "
                   "f22c40 df5320 c38418 7b9726 3d97b8 407ee7 6666ea c33ff3")),
)

BY_KEY = {family.key: family for family in FAMILIES}

# Material is not here, and the reason is a measurement rather than a taste: its
# light palette puts a teal (#80cbc4) in base05, the slot the format calls the
# default foreground, which is 1.8:1 against its own background. A terminal
# scheme can get away with that — it is drawing syntax highlighting, not
# paragraphs — and a page cannot. Nothing in its ground slots reaches 4.5:1 as a
# secondary ink either, so there was no arrangement of it worth offering.
#
# Which slot is the ink is chosen per palette rather than fixed at base05 for the
# same reason: see `_chosen` in `render.py`, where the pick is made by contrast
# and the numbers are asserted in `tests/test_themes.py`.


def luminance(colour: str) -> float:
    """WCAG relative luminance of `#rrggbb`."""
    channels = []
    for start in (1, 3, 5):
        value = int(colour[start:start + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.03928
                        else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: str, two: str) -> float:
    """WCAG contrast ratio between two `#rrggbb` colours, 1..21.

    Here rather than in the tests because it is the one thing worth ASKING of a
    scheme somebody hands us: sixteen colours that look lovely in a terminal can
    still put 2:1 text on a page, and this app is a page.
    """
    first, second = sorted((luminance(one), luminance(two)))
    return (second + 0.05) / (first + 0.05)
