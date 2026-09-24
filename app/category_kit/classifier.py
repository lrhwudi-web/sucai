from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PUTTER_SHAPE_CATEGORIES = {
    "HC_PUTTER_BLADE",
    "HC_PUTTER_MALLET_LARGE",
    "HC_PUTTER_MALLET_SMALL",
    "HC_PUTTER_SQUARE",
}
SPECIAL_PUTTER_RULES = {
    "putter_df3",
    "putter_df21",
    "putter_oz1",
    "putter_oz1i_hs",
}
HALF_RAW_CATEGORIES = {"半圆推杆套", "大半圆推杆套", "小半圆推杆套"}
POUCH_RAW_CATEGORIES = {"什物袋&装球袋", "什物袋", "装球袋"}
AUTO_REGISTRY_STATUSES = {"imported_verified", "derived_high", "human_approved"}


@dataclass(frozen=True)
class ProductInput:
    sku: str = ""
    name: str = ""
    english_name: str = ""
    path: str = ""
    raw_category: str = ""
    external_id: str = ""

    def normalized_sku(self) -> str:
        return self.sku.strip().upper()


@dataclass
class ClassificationResult:
    category_id: str
    category_label: str
    tags: list[str]
    confidence: float
    source: str
    rule_ids: list[str] = field(default_factory=list)
    reason: str = ""
    needs_review: bool = False
    conflicts: list[str] = field(default_factory=list)
    taxonomy_version: str = ""
    sku: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"\s+", " ", normalized).strip()


class Classifier:
    def __init__(
        self,
        package_dir: str | Path | None = None,
        *,
        registry_path: str | Path | None = None,
        store: Any | None = None,
    ) -> None:
        self.package_dir = Path(package_dir or Path(__file__).resolve().parents[1])
        self.taxonomy = self._load_json(self.package_dir / "config" / "taxonomy.json")
        self.rules_document = self._load_json(self.package_dir / "config" / "rules.json")
        self.taxonomy_version = str(self.taxonomy["version"])
        self.categories = {item["id"]: item for item in self.taxonomy["categories"]}
        self.raw_aliases = dict(self.taxonomy.get("raw_category_aliases", {}))
        self.rules = self._compile_rules(self.rules_document["rules"])
        self.tag_rules = self._compile_tag_rules(self.taxonomy.get("tags", []))
        self.registry_path = Path(registry_path or self.package_dir / "data" / "sku_registry.csv")
        self.registry = self._load_registry(self.registry_path)
        self.store = store

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _compile_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compiled: list[dict[str, Any]] = []
        for rule in rules:
            item = dict(rule)
            item["_any"] = [re.compile(pattern, re.IGNORECASE) for pattern in rule.get("patterns_any", [])]
            item["_none"] = [re.compile(pattern, re.IGNORECASE) for pattern in rule.get("patterns_none", [])]
            compiled.append(item)
        return sorted(compiled, key=lambda item: (-int(item["priority"]), item["id"]))

    @staticmethod
    def _compile_tag_rules(tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compiled: list[dict[str, Any]] = []
        for tag in tags:
            item = dict(tag)
            item["_any"] = [re.compile(pattern, re.IGNORECASE) for pattern in tag.get("patterns_any", [])]
            compiled.append(item)
        return compiled

    @staticmethod
    def _load_registry(path: Path) -> dict[str, dict[str, str]]:
        if not path.exists():
            return {}
        registry: dict[str, dict[str, str]] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                sku = (row.get("sku") or "").strip().upper()
                if sku:
                    registry[sku] = row
        return registry

    def _label(self, category_id: str) -> str:
        return self.categories.get(category_id, self.categories["UNKNOWN"])["label_zh"]

    def _tags(self, text: str) -> list[str]:
        return [
            tag["id"]
            for tag in self.tag_rules
            if any(pattern.search(text) for pattern in tag["_any"])
        ]

    def _rule_hits(self, text: str) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for rule in self.rules:
            if not any(pattern.search(text) for pattern in rule["_any"]):
                continue
            if any(pattern.search(text) for pattern in rule["_none"]):
                continue
            hits.append(rule)
        return hits

    def _unknown(self, product: ProductInput, tags: list[str], reason: str, conflicts: list[str] | None = None) -> ClassificationResult:
        return ClassificationResult(
            category_id="UNKNOWN",
            category_label=self._label("UNKNOWN"),
            tags=tags,
            confidence=0.0,
            source="unresolved",
            reason=reason,
            needs_review=True,
            conflicts=conflicts or [],
            taxonomy_version=self.taxonomy_version,
            sku=product.normalized_sku(),
        )

    def _from_registry(
        self,
        product: ProductInput,
        row: dict[str, str],
        text_result: ClassificationResult | None,
        tags: list[str],
        source: str,
    ) -> ClassificationResult:
        inherited_tags = [item for item in (row.get("tags") or "").split("|") if item]
        merged_tags = sorted(set(tags + inherited_tags))
        category_id = row.get("category_id") or "UNKNOWN"
        category_id = self.taxonomy.get("legacy_category_remap", {}).get(category_id, category_id)
        if "PLUSH_ANIMAL" in merged_tags:
            category_id = "HC_PLUSH"
        status = row.get("verification_status") or "needs_review"
        confidence = float(row.get("confidence") or 0)
        conflicts: list[str] = []
        needs_review = status not in AUTO_REGISTRY_STATUSES

        if text_result and text_result.category_id not in {"UNKNOWN", category_id} and text_result.confidence >= 0.95:
            conflicts.append(
                f"SKU继承分类={category_id}，文本强规则分类={text_result.category_id}"
            )
            needs_review = True

        reason = f"SKU {product.normalized_sku()} 继承已有分类；登记状态={status}"
        if conflicts:
            reason += "；检测到文本冲突，禁止自动通过"

        return ClassificationResult(
            category_id=category_id,
            category_label=self._label(category_id),
            tags=merged_tags,
            confidence=confidence,
            source=source,
            rule_ids=["sku_inheritance"],
            reason=reason,
            needs_review=needs_review,
            conflicts=conflicts,
            taxonomy_version=self.taxonomy_version,
            sku=product.normalized_sku(),
        )

    def _classify_text(self, product: ProductInput, text: str, tags: list[str]) -> ClassificationResult | None:
        hits = self._rule_hits(text)
        if not hits:
            return None

        selected = hits[0]
        conflicts: list[str] = []

        chinese_name = normalize_text(product.name)
        english_name = normalize_text(product.english_name)
        if "大半圆" in chinese_name and re.search(r"mid[-\s]?mallet", english_name):
            selected = next(
                (rule for rule in hits if rule["category_id"] == "HC_PUTTER_MALLET_LARGE"),
                selected,
            )
            conflicts.append("中文名称写大半圆，但英文名称写 Mid-Mallet")

        special_hits = [hit for hit in hits if hit["id"] in SPECIAL_PUTTER_RULES]
        shape_hits = [hit for hit in hits if hit["category_id"] in PUTTER_SHAPE_CATEGORIES]
        distinct_shapes = {hit["category_id"] for hit in shape_hits if float(hit["confidence"]) >= 0.95}
        if not special_hits and len(distinct_shapes) > 1:
            conflicts.append("同一产品同时命中多个互斥推杆形状：" + ", ".join(sorted(distinct_shapes)))

        needs_review = bool(selected.get("requires_review")) or bool(conflicts)
        confidence = float(selected["confidence"])
        if conflicts:
            confidence = min(confidence, 0.50)

        return ClassificationResult(
            category_id=selected["category_id"],
            category_label=self._label(selected["category_id"]),
            tags=tags,
            confidence=confidence,
            source="deterministic_rule",
            rule_ids=[hit["id"] for hit in hits],
            reason=selected["reason"],
            needs_review=needs_review,
            conflicts=conflicts,
            taxonomy_version=self.taxonomy_version,
            sku=product.normalized_sku(),
        )

    def classify(self, product: ProductInput) -> ClassificationResult:
        combined_text = normalize_text(
            " | ".join(
                [
                    product.name,
                    product.english_name,
                    product.path,
                ]
            )
        )
        tags = self._tags(combined_text)
        text_result = self._classify_text(product, combined_text, tags)
        sku = product.normalized_sku()

        if sku and self.store is not None:
            override = self.store.get_override(sku)
            if override:
                override_row = {
                    "category_id": override["category_id"],
                    "verification_status": "human_approved",
                    "confidence": "1.0",
                    "tags": override.get("tags", ""),
                }
                return self._from_registry(product, override_row, text_result, tags, "human_correction")

        if sku and sku in self.registry:
            return self._from_registry(product, self.registry[sku], text_result, tags, "sku_inheritance")

        raw_category = product.raw_category.strip()
        if raw_category in HALF_RAW_CATEGORIES:
            if text_result and text_result.category_id in PUTTER_SHAPE_CATEGORIES:
                return text_result
            return self._unknown(product, tags, "原分类只有“半圆”，名称不足以区分大半圆和小半圆")

        if raw_category in POUCH_RAW_CATEGORIES:
            if text_result and text_result.category_id in {"ACC_BALL_TEE_POUCH", "ACC_VALUABLES_POUCH"}:
                return text_result
            return self._unknown(product, tags, "原分类合并了什物袋与装球袋，名称不足以拆分")

        raw_id = self.raw_aliases.get(raw_category)
        if raw_id:
            if text_result and text_result.category_id != raw_id and text_result.confidence >= 0.95:
                return ClassificationResult(
                    category_id=raw_id,
                    category_label=self._label(raw_id),
                    tags=tags,
                    confidence=0.50,
                    source="raw_category_alias",
                    rule_ids=["raw_category_alias", *text_result.rule_ids],
                    reason=f"保留原分类“{raw_category}”，但文本强规则给出不同结果",
                    needs_review=True,
                    conflicts=[
                        f"原分类={raw_id}，文本强规则分类={text_result.category_id}"
                    ],
                    taxonomy_version=self.taxonomy_version,
                    sku=sku,
                )
            return ClassificationResult(
                category_id=raw_id,
                category_label=self._label(raw_id),
                tags=tags,
                confidence=0.99,
                source="raw_category_alias",
                rule_ids=["raw_category_alias"],
                reason=f"原分类“{raw_category}”精确映射到固定词典",
                needs_review=False,
                taxonomy_version=self.taxonomy_version,
                sku=sku,
            )

        if text_result:
            policy_min = float(self.taxonomy["review_policy"]["rule_auto_accept_min_confidence"])
            if text_result.confidence < policy_min:
                text_result.needs_review = True
            return text_result

        return self._unknown(product, tags, "未命中固定分类词典或确定性规则")
