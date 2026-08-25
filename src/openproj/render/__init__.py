"""The pages: everything the static export writes and everything the server draws.

Each page is one self-contained file. Libraries are inlined from `static/` rather
than linked, so a page works on a train and cannot be broken by a CDN. There is no
build step and no npm; the only JavaScript written here is vanilla.

Filter state lives in the query string. That makes every view a shareable URL,
makes the back button work, and deletes the entire saved-views feature request.

Derived values are drawn differently from stated ones throughout. A date the tool
computed, a size it guessed and work nobody owns are all forecasts, and a forecast
that looks like a commitment is how a timeline stops being believed.
"""

# A facade, and every name below is re-exported because something outside this
# package reads it — `web.py` through the module object, and the tests by
# import. The list is explicit and never `import *`, for two reasons: a star
# import skips the underscore names, and most of these are underscore names;
# and `test_table.py` asserts that `_NEW` and `render_new` are NOT attributes
# here, which an explicit list satisfies by construction.
#
# `__all__` names all of them so ruff's F401 needs no blanket noqa.

from ..vendor import _static_dir, _yjs
from .controls import (
    _COMBOBOX,
    _FILTER_JS,
    _combobox_html,
    _control_html,
    _cycle_numbers,
    _suggestions,
)
from .cycles import (
    _ROLE_FILTER,
    _ROLE_ORDER,
    _cycle_totals,
    _cycle_view,
    render_cycle,
    render_cycles,
    render_people,
)
from .deck import _bet_headings, render_deck, slide_html
from .detail import (
    _DETAIL,
    _TOC_LADDER,
    PROMOTABLE,
    _by_status,
    _detail_rows,
    _fact_rows,
    _shaping_hints,
    render_detail,
)
from .editor import _ACE_SURFACE, _COEDIT, ACE, PLAIN
from .env import _json
from .export import render_static
from .graph import _elements, render_graph
from .hill import (
    _HILL_ALONG,
    _HILL_BOX,
    _HILL_GROUND,
    _HILL_NORMALS,
    _HILL_OFF_THE_PATH,
    _HILL_STOPS,
    _LADDER_OF,
    _STATE_HINT,
    HILL_LADDERS,
    _hill_at,
    _hill_html,
    _hill_path,
    hill_geometry,
)
from .icons import _ICON_ART, ICONS, icon_svg
from .markdown import (
    _ASSET_MEDIA,
    _ASSET_SRC,
    _body_html,
    _drop_repeated_title,
    preview_html,
)
from .markdown import (
    _inlined_assets as inlined_assets,
)
from .records import render_records
from .rows import _row
from .shell import _SHELL, CSP, ROUTES, STATIC, _page
from .slides import render_slide_editor
from .styles import STATUS_SLOTS, _chosen, _scheme_css
from .table import (
    _TABLE_COLUMNS,
    _TABLE_DERIVED,
    _columns_for,
    _new_row_fields,
    _payload,
    render_table,
)
from .timeline import (
    _MARK_WORDS,
    _MIN_BAR_PX,
    _ROW_PX,
    _containment_rows,
    _month_ticks,
    _timeline,
    render_timeline,
)
from .tokens import (
    _KIND_MODELS,
    _TASK_TEMPLATE,
    EDITABLE,
    FIELD_TEACH,
    HUMAN,
    KINDS,
    LABELS,
    PREFIX,
    PRIORITIES,
    PRIORITY_GLYPH,
    REQUIRED_AT,
    STATUS_GLYPH,
    STATUS_TEACH,
    STATUSES,
    SUGGESTS,
    TEMPLATES,
    _ago,
    _editable_for,
    _human,
)

__all__ = [
    "ACE",
    "CSP",
    "EDITABLE",
    "FIELD_TEACH",
    "HILL_LADDERS",
    "HUMAN",
    "ICONS",
    "KINDS",
    "LABELS",
    "PLAIN",
    "PREFIX",
    "PRIORITIES",
    "PRIORITY_GLYPH",
    "PROMOTABLE",
    "REQUIRED_AT",
    "ROUTES",
    "STATIC",
    "STATUSES",
    "STATUS_GLYPH",
    "STATUS_SLOTS",
    "STATUS_TEACH",
    "SUGGESTS",
    "TEMPLATES",
    "_ACE_SURFACE",
    "_ASSET_MEDIA",
    "_ASSET_SRC",
    "_COEDIT",
    "_COMBOBOX",
    "_DETAIL",
    "_FILTER_JS",
    "_HILL_ALONG",
    "_HILL_BOX",
    "_HILL_GROUND",
    "_HILL_NORMALS",
    "_HILL_OFF_THE_PATH",
    "_HILL_STOPS",
    "_ICON_ART",
    "_KIND_MODELS",
    "_LADDER_OF",
    "_MARK_WORDS",
    "_MIN_BAR_PX",
    "_ROLE_FILTER",
    "_ROLE_ORDER",
    "_ROW_PX",
    "_containment_rows",
    "_month_ticks",
    "_SHELL",
    "_STATE_HINT",
    "_TABLE_COLUMNS",
    "_TABLE_DERIVED",
    "_TASK_TEMPLATE",
    "_TOC_LADDER",
    "_ago",
    "_bet_headings",
    "_body_html",
    "_by_status",
    "_chosen",
    "_columns_for",
    "_combobox_html",
    "_control_html",
    "_cycle_numbers",
    "_cycle_totals",
    "_cycle_view",
    "_detail_rows",
    "_drop_repeated_title",
    "_editable_for",
    "_elements",
    "_fact_rows",
    "_hill_at",
    "_hill_html",
    "_hill_path",
    "_human",
    "_json",
    "_new_row_fields",
    "_page",
    "_payload",
    "_row",
    "_scheme_css",
    "_shaping_hints",
    "_static_dir",
    "_suggestions",
    "_timeline",
    "_yjs",
    "hill_geometry",
    "icon_svg",
    "preview_html",
    "render_cycle",
    "render_cycles",
    "render_deck",
    "render_slide_editor",
    "slide_html",
    "inlined_assets",
    "render_detail",
    "render_graph",
    "render_people",
    "render_records",
    "render_static",
    "render_table",
    "render_timeline",
]
