"""Export of the screen specs to Figma as a generated plugin (ADR-0030, plan M15 step 5).

Figma's REST API only reads, so the platform writes a development plugin instead: a ZIP with `manifest.json` and
`code.js`, the screens and the design tokens inlined as data. A person imports it in Figma desktop (Plugins →
Development → Import plugin from manifest) and runs it once; it creates one page per module (the BMS mapset, or
"NexTI screens") and one frame per screen with its fields as labelled input-like groups, its actions as buttons and
its states (empty, loading, error, success) as frames side by side, coloured and typed with local styles made from
the tokens. The script is the same text for the same screens: no network, no eval, no timestamps, only the screens'
own content (never the legacy source references).

The input is the screen spec as stored (`ScreenSpec.model_dump(mode="json")`, spec 4.1), so this package needs no
dependency on the spec model; anything missing or malformed falls back to a neutral value."""

import io
import json
import re
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any

from nexti_ui import base_tokens

PLUGIN_NAME = "NexTI screens"
PLUGIN_ID = "nexti-screens-export"
DEFAULT_MODULE = "NexTI screens"
STATES = ("empty", "loading", "error", "success")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PX = re.compile(r"^(\d{1,3})(px)?$")
_WEIGHTS = {400: "Regular", 500: "Medium", 600: "Semi Bold", 700: "Bold"}
# The text styles the plugin creates: name → (font size token, font weight token).
_TEXT_STYLES = {"title": ("xl", "bold"), "heading": ("lg", "medium"), "body": ("md", "regular"),
                "label": ("sm", "medium"), "hint": ("xs", "regular")}  # fmt: skip
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _text(value: Any, limit: int = 500) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _field(raw: Mapping[str, Any]) -> dict[str, Any]:
    kind = raw.get("kind") if raw.get("kind") in ("input", "output", "literal") else "output"
    length = raw.get("length")
    return {
        "name": _text(raw.get("name"), 64) or "FIELD",
        "kind": kind,
        "label": _text(raw.get("label"), 200),
        "type": _text(raw.get("type"), 100),
        "length": length if isinstance(length, int) and length >= 0 else 0,
        "required": raw.get("required") is True,
        "format": _text(raw.get("format"), 100),
        "validation": _text(raw.get("validation")),
        "message": _text(raw.get("message"), 200),
        "initial": _text(raw.get("initial"), 200) if kind == "literal" else "",
    }


def _screen(raw: Mapping[str, Any]) -> dict[str, Any]:
    fields = [_field(f) for f in raw.get("fields") or () if isinstance(f, Mapping)]
    actions = [
        {"key": _text(a.get("key"), 40) or "ACTION", "label": _text(a.get("label"), 100),
         "target": _text(a.get("target"), 50)}
        for a in raw.get("actions") or () if isinstance(a, Mapping)
    ]  # fmt: skip
    declared = [s for s in raw.get("states") or () if s in STATES]
    # A screen that declares no states still gets the four the UI phase designs for every screen (spec 7.4).
    states = [s for s in STATES if s in declared] if declared else list(STATES)
    return {
        "id": _text(raw.get("id"), 50) or "SCR-UNKNOWN",
        "name": _text(raw.get("name"), 200),
        "module": _text(raw.get("mapset"), 100) or DEFAULT_MODULE,
        "fields": fields,
        "actions": actions,
        "states": states,
    }


def _px(value: Any, fallback: int) -> int:
    match = _PX.match(str(value).strip()) if isinstance(value, (str, int)) else None
    return int(match.group(1)) if match and 0 < int(match.group(1)) <= 200 else fallback


def _family(value: Any) -> str:
    first = value.split(",")[0].strip().strip("'\"") if isinstance(value, str) else ""
    return first if re.fullmatch(r"[A-Za-z0-9 ]{1,60}", first) else "Inter"


def styles(tokens: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The colours and text styles the plugin creates, from the project's tokens over the NexTI base ones."""
    try:
        base = base_tokens()
    except OSError:  # an install without the design system sources: the project's own tokens only
        base = {}
    given = tokens if isinstance(tokens, Mapping) else {}
    colours: dict[str, str] = {}
    for source in (base.get("color", {}), given.get("color", {})):
        if isinstance(source, Mapping):
            colours.update({k: v.lower() for k, v in source.items()
                            if isinstance(k, str) and isinstance(v, str) and _HEX.match(v)})  # fmt: skip
    base_font: Mapping[str, Any] = base.get("font", {})
    font: Mapping[str, Any] = given.get("font") if isinstance(given.get("font"), Mapping) else base_font  # type: ignore[assignment]

    def token(group: str, key: str) -> Any:
        for source in (font, base_font):
            values = source.get(group)
            if isinstance(values, Mapping) and key in values:
                return values[key]
        return None

    text = {}
    for name, (size, weight) in _TEXT_STYLES.items():
        number = token("weight", weight)
        text[name] = {"size": _px(token("size", size), 14),
                      "style": _WEIGHTS.get(number if isinstance(number, int) else 400, "Regular")}  # fmt: skip
    return {"family": _family(font.get("family", base_font.get("family"))), "colors": dict(sorted(colours.items())),
            "text": text}  # fmt: skip


def plugin_data(screens: Sequence[Mapping[str, Any]], tokens: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The data inlined in code.js: the screens grouped by module (sorted, so the output is stable) and the styles."""
    normalized = sorted((_screen(s) for s in screens), key=lambda s: (s["module"], s["id"]))
    modules: dict[str, list[dict[str, Any]]] = {}
    for screen in normalized:
        modules.setdefault(screen.pop("module"), []).append(screen)
    return {"modules": [{"name": name, "screens": items} for name, items in modules.items()],
            "styles": styles(tokens)}  # fmt: skip


def manifest() -> dict[str, Any]:
    """The Figma plugin manifest: a development plugin for the design editor that never reaches the network."""
    return {
        "name": PLUGIN_NAME,
        "id": PLUGIN_ID,
        "api": "1.0.0",
        "main": "code.js",
        "editorType": ["figma"],
        "documentAccess": "dynamic-page",
        "networkAccess": {"allowedDomains": ["none"]},
    }


# The plugin itself. Only the Figma plugin API and plain JavaScript: no network, no eval, no clock, no randomness.
_RUNTIME = r"""
const SCREEN_WIDTH = 960;
const STATE_WIDTH = 216;
const GAP = 120;
const COLUMNS = 2;

function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 };
}

function solid(name) {
  return [{ type: 'SOLID', color: rgb(DATA.styles.colors[name] || '#000000') }];
}

async function paintStyles() {
  const existing = figma.getLocalPaintStylesAsync ? await figma.getLocalPaintStylesAsync() : [];
  const found = {};
  for (const name of Object.keys(DATA.styles.colors)) {
    const full = 'NexTI/color/' + name;
    let style = existing.find((s) => s.name === full);
    if (!style) {
      style = figma.createPaintStyle();
      style.name = full;
    }
    style.paints = solid(name);
    found[name] = style;
  }
  return found;
}

async function loadFonts() {
  const wanted = [...new Set(Object.values(DATA.styles.text).map((t) => t.style))].sort();
  for (const family of [DATA.styles.family, 'Inter']) {
    try {
      for (const style of wanted) await figma.loadFontAsync({ family, style });
      return family;
    } catch (error) {
      // The family is not installed: fall back to Inter, which Figma always has.
    }
  }
  throw new Error('No usable font');
}

async function textStyles(family) {
  const existing = figma.getLocalTextStylesAsync ? await figma.getLocalTextStylesAsync() : [];
  const found = {};
  for (const name of Object.keys(DATA.styles.text)) {
    const spec = DATA.styles.text[name];
    const full = 'NexTI/text/' + name;
    let style = existing.find((s) => s.name === full);
    if (!style) {
      style = figma.createTextStyle();
      style.name = full;
    }
    style.fontName = { family, style: spec.style };
    style.fontSize = spec.size;
    found[name] = style;
  }
  return found;
}

async function fill(node, style, colour) {
  node.fills = solid(colour);
  if (style[colour] && node.setFillStyleIdAsync) await node.setFillStyleIdAsync(style[colour].id);
}

async function label(ctx, parent, name, characters, kind, colour) {
  const node = figma.createText();
  node.name = name;
  const spec = DATA.styles.text[kind];
  node.fontName = { family: ctx.family, style: spec.style };
  node.fontSize = spec.size;
  node.characters = characters;
  if (node.setTextStyleIdAsync) await node.setTextStyleIdAsync(ctx.text[kind].id);
  await fill(node, ctx.paint, colour || 'text');
  parent.appendChild(node);
  return node;
}

function box(name, direction, spacing, padding) {
  const node = figma.createFrame();
  node.name = name;
  node.layoutMode = direction;
  node.primaryAxisSizingMode = 'AUTO';
  node.counterAxisSizingMode = 'AUTO';
  node.itemSpacing = spacing;
  node.paddingTop = padding;
  node.paddingBottom = padding;
  node.paddingLeft = padding;
  node.paddingRight = padding;
  node.fills = [];
  return node;
}

function hint(field) {
  const parts = [];
  if (field.format) parts.push('Format: ' + field.format);
  if (field.validation) parts.push('Validation: ' + field.validation);
  if (field.message) parts.push('Error: ' + field.message);
  return parts.join(' · ');
}

async function fieldGroup(ctx, parent, field) {
  if (field.kind === 'literal') {
    await label(ctx, parent, 'field:' + field.name, field.initial || field.label || field.name, 'body', 'textMuted');
    return;
  }
  const group = box('field:' + field.name, 'VERTICAL', 4, 0);
  const caption = (field.label || field.name) + (field.required ? ' *' : '');
  await label(ctx, group, 'label', caption, 'label', 'text');
  const input = box('input', 'HORIZONTAL', 8, 8);
  input.resize(360, 36);
  input.primaryAxisSizingMode = 'FIXED';
  input.counterAxisSizingMode = 'FIXED';
  input.cornerRadius = 4;
  await fill(input, ctx.paint, field.kind === 'input' ? 'surface' : 'surfaceMuted');
  input.strokes = solid('border');
  input.strokeWeight = 1;
  const type = (field.type || field.kind) + (field.length ? ' (' + field.length + ')' : '');
  await label(ctx, input, 'type', type, 'hint', 'textMuted');
  group.appendChild(input);
  if (field.required) await label(ctx, group, 'required', 'Required', 'hint', 'danger');
  const text = hint(field);
  if (text) await label(ctx, group, 'hint', text, 'hint', 'textMuted');
  parent.appendChild(group);
}

async function button(ctx, parent, action, primary) {
  const node = box('action:' + action.key, 'HORIZONTAL', 0, 8);
  node.paddingLeft = 16;
  node.paddingRight = 16;
  node.cornerRadius = 4;
  await fill(node, ctx.paint, primary ? 'primary' : 'surface');
  node.strokes = solid(primary ? 'primary' : 'border');
  node.strokeWeight = 1;
  const caption = action.label ? action.label + ' (' + action.key + ')' : action.key;
  await label(ctx, node, 'label', caption, 'label', primary ? 'primaryContrast' : 'text');
  parent.appendChild(node);
}

const STATE_TEXT = {
  empty: ['surfaceMuted', 'text', 'Empty: nothing to show yet'],
  loading: ['surfaceMuted', 'textMuted', 'Loading…'],
  error: ['danger', 'primaryContrast', 'Error'],
  success: ['success', 'primaryContrast', 'Success'],
};

async function stateFrame(ctx, parent, screen, state) {
  const node = box('state:' + state, 'VERTICAL', 8, 16);
  node.resize(STATE_WIDTH, 120);
  node.counterAxisSizingMode = 'FIXED';
  node.cornerRadius = 8;
  const look = STATE_TEXT[state];
  await fill(node, ctx.paint, look[0]);
  await label(ctx, node, 'state', state.toUpperCase(), 'label', look[1]);
  let detail = look[2];
  if (state === 'error') {
    const message = screen.fields.find((f) => f.message);
    if (message) detail = message.message;
  }
  await label(ctx, node, 'detail', detail, 'hint', look[1]);
  parent.appendChild(node);
}

async function screenFrame(ctx, page, screen) {
  const frame = box(screen.id + ' — ' + screen.name, 'VERTICAL', 24, 32);
  frame.resize(SCREEN_WIDTH, 400);
  frame.counterAxisSizingMode = 'FIXED';
  frame.cornerRadius = 12;
  await fill(frame, ctx.paint, 'surface');
  frame.strokes = solid('border');
  frame.strokeWeight = 1;
  await label(ctx, frame, 'title', screen.name || screen.id, 'title', 'text');
  await label(ctx, frame, 'id', screen.id, 'hint', 'textMuted');
  const fields = box('fields', 'VERTICAL', 16, 0);
  for (const field of screen.fields) await fieldGroup(ctx, fields, field);
  frame.appendChild(fields);
  const actions = box('actions', 'HORIZONTAL', 8, 0);
  for (let i = 0; i < screen.actions.length; i++) await button(ctx, actions, screen.actions[i], i === 0);
  frame.appendChild(actions);
  await label(ctx, frame, 'states-title', 'States', 'heading', 'text');
  const states = box('states', 'HORIZONTAL', 16, 0);
  for (const state of screen.states) await stateFrame(ctx, states, screen, state);
  frame.appendChild(states);
  page.appendChild(frame);
  return frame;
}

function grid(frames) {
  let y = 0;
  for (let start = 0; start < frames.length; start += COLUMNS) {
    const row = frames.slice(start, start + COLUMNS);
    let tallest = 0;
    row.forEach((frame, i) => {
      frame.x = i * (SCREEN_WIDTH + GAP);
      frame.y = y;
      tallest = Math.max(tallest, frame.height || 0);
    });
    y += tallest + GAP;
  }
}

async function main() {
  const family = await loadFonts();
  const ctx = { family, paint: await paintStyles(), text: await textStyles(family) };
  let count = 0;
  let first = null;
  for (const module of DATA.modules) {
    const page = figma.createPage();
    page.name = module.name;
    if (!first) first = page;
    const frames = [];
    for (const screen of module.screens) frames.push(await screenFrame(ctx, page, screen));
    grid(frames);
    count += frames.length;
  }
  if (first && figma.setCurrentPageAsync) await figma.setCurrentPageAsync(first);
  return 'NexTI: ' + count + ' screens exported to ' + DATA.modules.length + ' pages';
}

main().then(
  (message) => figma.closePlugin(message),
  (error) => figma.closePlugin('NexTI export failed: ' + (error && error.message ? error.message : error)),
);
"""


def code_js(screens: Sequence[Mapping[str, Any]], tokens: Mapping[str, Any] | None = None) -> str:
    """The plugin script with the data inlined as a JSON literal (ASCII only, so no line separators leak in)."""
    data = json.dumps(plugin_data(screens, tokens), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    header = "// NexTI screens for Figma, generated by the platform (ADR-0030). Deterministic, no network access.\n"
    return f"{header}const DATA = {data};\n{_RUNTIME.lstrip()}"


def export_zip(screens: Sequence[Mapping[str, Any]], tokens: Mapping[str, Any] | None = None) -> bytes:
    """The plugin as a ZIP: the same bytes for the same screens and tokens (fixed order, dates and permissions)."""
    if not screens:
        raise ValueError("there are no screens to export")
    files = {
        "manifest.json": json.dumps(manifest(), indent=2, sort_keys=False) + "\n",
        "code.js": code_js(screens, tokens),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()


__all__ = ["DEFAULT_MODULE", "PLUGIN_ID", "PLUGIN_NAME", "STATES", "code_js", "export_zip", "manifest", "plugin_data",
           "styles"]  # fmt: skip
