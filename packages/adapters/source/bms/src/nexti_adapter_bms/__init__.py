"""The BMS map adapter (spec 8.2 `screens()`, 8.3): recognises mapsets, parses them deterministically and turns every
map into a screen spec with each field's position, length and attributes. It never uses a model and never executes
anything; its inventory adds the maps and their fields to the code layer of the knowledge graph."""

import re

from nexti_adapter_bms.parser import BmsError, BmsField, BmsMap, Mapset, parse
from nexti_adapter_bms.screens import picture_type, screen_spec
from nexti_core.adapters import Edge, Inventory, Node, SourceFile
from nexti_core.spec.screens import ScreenSpec

EXTENSIONS = (".bms", ".map", ".mac")
_MACRO = re.compile(r"\bDFHM(SD|DI|DF)\b")


class BmsAdapter:
    name = "cics-bms"

    def _files(self, files: list[SourceFile]) -> list[SourceFile]:
        return [f for f in files if f.path.lower().endswith(EXTENSIONS) or _MACRO.search(f.text)]

    def detect(self, files: list[SourceFile]) -> float:
        candidates = self._files(files)
        if not candidates:
            return 0.0
        macros = sum(min(len(_MACRO.findall(f.text)), 20) for f in candidates)
        return round(min(1.0, 0.5 + macros / (40 * len(candidates))), 2)

    def mapsets(self, files: list[SourceFile]) -> list[tuple[SourceFile, Mapset]]:
        return [(f, m) for f in self._files(files) for m in parse(f.text)]

    def screens(self, files: list[SourceFile]) -> list[ScreenSpec]:
        return [screen_spec(m, f.path, s.name) for f, s in self.mapsets(files) for m in s.maps]

    def inventory(self, files: list[SourceFile]) -> Inventory:
        inv = Inventory(self.name)
        for file, mapset in self.mapsets(files):
            inv.nodes.append(Node(f"mapset:{mapset.name}", "Mapset", mapset.name, file=file.path,
                                  line_start=mapset.line_start, line_end=mapset.line_start))  # fmt: skip
            for bms_map in mapset.maps:
                map_key = f"map:{mapset.name}.{bms_map.name}"
                inv.nodes.append(Node(map_key, "BmsMap", bms_map.name, file=file.path, line_start=bms_map.line_start,
                                      line_end=bms_map.line_end,
                                      properties={"rows": bms_map.rows, "columns": bms_map.columns}))  # fmt: skip
                inv.edges.append(Edge(f"mapset:{mapset.name}", "CONTAINS", map_key))
                for bms in bms_map.fields:
                    if bms.label is None:
                        continue
                    key = f"{map_key}.{bms.label}"
                    inv.nodes.append(Node(key, "Field", bms.label, file=file.path, line_start=bms.line_start,
                                          line_end=bms.line_end, properties={
                                              "row": bms.row, "column": bms.column, "length": bms.length,
                                              "attributes": ",".join(bms.attributes),
                                              "neutral_type": picture_type(bms.picin or bms.picout, bms.length),
                                          }))  # fmt: skip
                    inv.edges.append(Edge(map_key, "CONTAINS", key))
        inv.metrics = {"mapsets": sum(1 for n in inv.nodes if n.label == "Mapset"),
                       "maps": sum(1 for n in inv.nodes if n.label == "BmsMap"),
                       "fields": sum(1 for n in inv.nodes if n.label == "Field")}  # fmt: skip
        return inv


__all__ = ["BmsAdapter", "BmsError", "BmsField", "BmsMap", "Mapset", "parse", "picture_type", "screen_spec"]
