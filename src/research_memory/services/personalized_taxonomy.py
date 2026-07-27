from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable

from research_memory.contracts import (
    NavigationOverride,
    PersonalizedTaxonomyNode,
    PersonalizedTaxonomyTree,
    ResearchProfile,
)
from research_memory.services.taxonomy_catalog import (
    PackMembershipRecord,
    SpecialtyPackRecord,
    TaxonomyCatalog,
)


class PersonalizedTaxonomyBuilder:
    """Pure deterministic builder for profile-specific display trees."""

    _visible_depth = {"broad": 2, "balanced": 4, "detailed": 8}

    def __init__(self, catalog: TaxonomyCatalog):
        self.catalog = catalog
        self._canonical_children: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for edge in catalog.edges:
            if edge.edge_type in {"is_a", "part_of", "display_under"}:
                self._canonical_children[edge.parent_id].append((edge.sort_order, edge.child_id))
        for children in self._canonical_children.values():
            children.sort(
                key=lambda item: (
                    item[0],
                    self.catalog.nodes_by_id[item[1]].canonical_name.casefold(),
                    item[1],
                )
            )
        self._packs_for_selection: dict[str, list[SpecialtyPackRecord]] = defaultdict(list)
        for pack in catalog.packs:
            self._packs_for_selection[pack.selection_node_id].append(pack)

    def build(self, profile: ResearchProfile) -> PersonalizedTaxonomyTree:
        warnings: list[str] = []
        roots: list[PersonalizedTaxonomyNode] = []
        root_sort_order: dict[str, int] = {}

        selected_weights: dict[str, float] = {}
        for selection in profile.selections:
            selected_weights[selection.node_id] = max(
                selection.priority_weight,
                selected_weights.get(selection.node_id, 0),
            )

        for selection_index, (node_id, weight) in enumerate(
            sorted(
                selected_weights.items(),
                key=lambda item: (
                    -item[1],
                    self.catalog.nodes_by_id[item[0]].canonical_name.casefold()
                    if item[0] in self.catalog.nodes_by_id
                    else item[0],
                ),
            )
        ):
            node = self.catalog.get_node(node_id)
            if node is None:
                warnings.append(f"Profile selection does not resolve: {node_id}")
                continue
            if node.status == "retired":
                warnings.append(f"Profile selection uses retired node snapshot: {node_id}")
            direct_packs = sorted(
                self._packs_for_selection.get(node_id, []),
                key=lambda item: item.pack_id,
            )
            if not direct_packs:
                display_id = self._display_id("direct", "", node_id)
                roots.append(
                    PersonalizedTaxonomyNode(
                        canonical_node_id=node_id,
                        display_instance_id=display_id,
                        display_name=node.canonical_name,
                        node_type=node.node_type,
                        weight=weight,
                        depth=0,
                    )
                )
                root_sort_order[display_id] = selection_index
                continue
            for pack in direct_packs:
                root = self._build_pack_root(pack, weight)
                roots.append(root)
                root_sort_order[root.display_instance_id] = selection_index

        self._apply_overrides(roots, profile.navigation_overrides, warnings)
        depth_limit = self._visible_depth[profile.hierarchy_depth]
        hidden_ids = {
            override.node_id
            for override in profile.navigation_overrides
            if override.action == "hide"
        }
        override_order = {
            override.node_id: override.sort_order
            for override in profile.navigation_overrides
            if override.action == "pin"
        }
        self._finalize_tree(
            roots,
            depth=0,
            parent_id=None,
            depth_limit=depth_limit,
            ancestor_visible=True,
            hidden_ids=hidden_ids,
            override_order=override_order,
        )
        roots.sort(
            key=lambda item: (
                not item.pinned,
                override_order.get(
                    item.canonical_node_id,
                    root_sort_order.get(item.display_instance_id, 0),
                ),
                -item.weight,
                item.display_name.casefold(),
                item.display_instance_id,
            )
        )
        canonical_ids = {item.canonical_node_id for item in self._walk_nodes(roots)}
        return PersonalizedTaxonomyTree(
            catalog_version=self.catalog.manifest.catalog_version,
            profile_revision=self.profile_revision(profile),
            warnings=warnings,
            roots=roots,
            total_canonical_nodes=len(canonical_ids),
        )

    def _build_pack_root(
        self, pack: SpecialtyPackRecord, weight: float
    ) -> PersonalizedTaxonomyNode:
        root_node = self.catalog.nodes_by_id[pack.selection_node_id]
        root_id = self._display_id(pack.pack_id, "", root_node.id)
        root = PersonalizedTaxonomyNode(
            canonical_node_id=root_node.id,
            display_instance_id=root_id,
            display_name=root_node.canonical_name,
            node_type=root_node.node_type,
            weight=weight,
            depth=0,
        )
        resolved_packs = self._resolve_packs(pack)
        memberships: list[PackMembershipRecord] = []
        membership_keys: set[tuple[str, str | None, str]] = set()
        for resolved in resolved_packs:
            for membership in resolved.memberships:
                key = (
                    membership.node_id,
                    membership.display_parent_node_id,
                    membership.membership_role,
                )
                if key not in membership_keys:
                    memberships.append(membership)
                    membership_keys.add(key)

        by_parent: dict[str | None, list[PackMembershipRecord]] = defaultdict(list)
        for membership in memberships:
            by_parent[membership.display_parent_node_id].append(membership)
        for values in by_parent.values():
            values.sort(
                key=lambda item: (
                    item.sort_order,
                    self.catalog.nodes_by_id[item.node_id].canonical_name.casefold(),
                    item.node_id,
                )
            )
        root.children = self._expand_children(
            pack_id=pack.pack_id,
            parent=root,
            parent_canonical_id=root_node.id,
            root_memberships=by_parent[None],
            memberships_by_parent=by_parent,
            weight=weight,
            trail=(root_node.id,),
        )
        return root

    def _expand_children(
        self,
        *,
        pack_id: str,
        parent: PersonalizedTaxonomyNode,
        parent_canonical_id: str,
        root_memberships: list[PackMembershipRecord] | None,
        memberships_by_parent: dict[str | None, list[PackMembershipRecord]],
        weight: float,
        trail: tuple[str, ...],
    ) -> list[PersonalizedTaxonomyNode]:
        candidates: list[tuple[int, str]] = []
        explicit = (
            root_memberships
            if root_memberships is not None
            else memberships_by_parent.get(parent_canonical_id, [])
        )
        candidates.extend((membership.sort_order, membership.node_id) for membership in explicit)
        candidates.extend(self._canonical_children.get(parent_canonical_id, []))

        result: list[PersonalizedTaxonomyNode] = []
        seen_under_parent: set[str] = set()
        for _order, node_id in sorted(
            candidates,
            key=lambda item: (
                item[0],
                self.catalog.nodes_by_id[item[1]].canonical_name.casefold(),
                item[1],
            ),
        ):
            if node_id in seen_under_parent or node_id in trail:
                continue
            seen_under_parent.add(node_id)
            node = self.catalog.nodes_by_id[node_id]
            display_id = self._display_id(pack_id, parent.display_instance_id, node_id)
            child = PersonalizedTaxonomyNode(
                canonical_node_id=node_id,
                display_instance_id=display_id,
                parent_display_instance_id=parent.display_instance_id,
                display_name=node.canonical_name,
                node_type=node.node_type,
                weight=weight,
                depth=parent.depth + 1,
            )
            child.children = self._expand_children(
                pack_id=pack_id,
                parent=child,
                parent_canonical_id=node_id,
                root_memberships=None,
                memberships_by_parent=memberships_by_parent,
                weight=weight,
                trail=(*trail, node_id),
            )
            result.append(child)
        return result

    def _resolve_packs(self, root: SpecialtyPackRecord) -> list[SpecialtyPackRecord]:
        result: list[SpecialtyPackRecord] = []
        visited: set[str] = set()

        def add(pack: SpecialtyPackRecord) -> None:
            if pack.pack_id in visited:
                return
            visited.add(pack.pack_id)
            result.append(pack)
            for inherited_id in sorted(pack.inherits):
                add(self.catalog.packs_by_id[inherited_id])

        add(root)
        return result

    def _apply_overrides(
        self,
        roots: list[PersonalizedTaxonomyNode],
        overrides: list[NavigationOverride],
        warnings: list[str],
    ) -> None:
        for override in overrides:
            instances = [
                item
                for item in self._walk_nodes(roots)
                if item.canonical_node_id == override.node_id
            ]
            if not instances:
                warnings.append(
                    f"Navigation override node is not present in this tree: {override.node_id}"
                )
                continue
            if override.action == "alias":
                if not override.display_alias:
                    warnings.append(f"Alias override has no display alias: {override.node_id}")
                else:
                    for item in instances:
                        item.display_name = override.display_alias
            elif override.action == "pin":
                for item in instances:
                    item.pinned = True
            elif override.action == "move":
                if override.display_parent_node_id is None:
                    warnings.append(f"Move override has no display parent: {override.node_id}")
                    continue
                self._move_first_instance(
                    roots,
                    instances[0],
                    override.display_parent_node_id,
                    warnings,
                )

    def _move_first_instance(
        self,
        roots: list[PersonalizedTaxonomyNode],
        source: PersonalizedTaxonomyNode,
        destination_node_id: str,
        warnings: list[str],
    ) -> None:
        destination = next(
            (
                item
                for item in self._walk_nodes(roots)
                if item.canonical_node_id == destination_node_id
                and item.display_instance_id != source.display_instance_id
            ),
            None,
        )
        if destination is None:
            warnings.append(
                f"Move override destination is not present in this tree: {destination_node_id}"
            )
            return
        if destination.display_instance_id in {
            item.display_instance_id for item in self._walk_nodes([source])
        }:
            warnings.append(
                f"Move override would create a display cycle: {source.canonical_node_id}"
            )
            return
        if not self._remove_instance(roots, source.display_instance_id):
            return
        source.parent_display_instance_id = destination.display_instance_id
        destination.children.append(source)

    def _remove_instance(self, nodes: list[PersonalizedTaxonomyNode], display_id: str) -> bool:
        for index, item in enumerate(nodes):
            if item.display_instance_id == display_id:
                nodes.pop(index)
                return True
            if self._remove_instance(item.children, display_id):
                return True
        return False

    def _finalize_tree(
        self,
        nodes: list[PersonalizedTaxonomyNode],
        *,
        depth: int,
        parent_id: str | None,
        depth_limit: int,
        ancestor_visible: bool,
        hidden_ids: set[str],
        override_order: dict[str, int],
    ) -> None:
        for item in nodes:
            item.depth = depth
            item.parent_display_instance_id = parent_id
            item.visible = (
                ancestor_visible
                and depth <= depth_limit
                and item.canonical_node_id not in hidden_ids
            )
            self._finalize_tree(
                item.children,
                depth=depth + 1,
                parent_id=item.display_instance_id,
                depth_limit=depth_limit,
                ancestor_visible=item.visible,
                hidden_ids=hidden_ids,
                override_order=override_order,
            )
            item.children.sort(
                key=lambda child: (
                    not child.pinned,
                    override_order.get(child.canonical_node_id, 0),
                    -child.weight,
                    child.display_name.casefold(),
                    child.display_instance_id,
                )
            )

    @staticmethod
    def _walk_nodes(
        roots: Iterable[PersonalizedTaxonomyNode],
    ) -> Iterable[PersonalizedTaxonomyNode]:
        for root in roots:
            yield root
            yield from PersonalizedTaxonomyBuilder._walk_nodes(root.children)

    @staticmethod
    def _display_id(pack_id: str, parent_id: str, node_id: str) -> str:
        value = f"{pack_id}|{parent_id}|{node_id}".encode()
        return "display." + hashlib.sha256(value).hexdigest()[:24]

    @staticmethod
    def profile_revision(profile: ResearchProfile) -> str:
        data = profile.model_dump(mode="json", exclude={"created_at", "updated_at"})
        payload = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return hashlib.sha256(payload).hexdigest()[:24]
