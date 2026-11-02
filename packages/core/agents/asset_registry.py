"""Semantic Asset Registry for ShortsFactoryAI-Studio.

Maps narrative concepts and visual requirements to verified, drawable SVG objects and environments
in packages/video/src/art/ without hardcoded topic hacks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..contracts.scene import ENVIRONMENTS, OBJECT_KINDS, OBJECT_LABELS


@dataclass(frozen=True)
class AssetDescriptor:
    kind: str
    label: str
    category: str
    semantic_tags: tuple[str, ...]
    capabilities: tuple[str, ...]
    composable_with: tuple[str, ...]
    preferred_environments: tuple[str, ...]
    source: str = "packages/video/src/art/objects.tsx"
    license: str = "project-original"


# Semantic metadata for all local drawable objects
ASSET_DESCRIPTORS: dict[str, AssetDescriptor] = {
    # Telecommunications & Subsea Infrastructure
    "subseaCableCutaway": AssetDescriptor(
        kind="subseaCableCutaway",
        label="Kabel Bawah Laut (Cross-Section)",
        category="infrastructure",
        semantic_tags=(
            "kabel", "cable", "subsea", "laut", "dasar laut", "bawah laut", "ocean",
            "serat optik", "fiber", "fiber optic", "optical fiber", "transmisi data",
            "lapisan", "cutaway", "penampang", "selang", "internet global", "trench",
            "samudra", "pelindung", "tembaga", "polietilena", "kawat baja"
        ),
        capabilities=("hero_subject", "cross_section", "detail_zoom", "process_node"),
        composable_with=("opticalFiber", "satellite", "dataCenter"),
        preferred_environments=("oceanFloor", "abstract", "grid"),
    ),
    "opticalFiber": AssetDescriptor(
        kind="opticalFiber",
        label="Optical Fiber",
        category="infrastructure",
        semantic_tags=(
            "fiber", "serat", "optik", "optical", "glass", "kaca", "laser", "cahaya",
            "light pulse", "sinyal", "pulsa", "transmisi", "kecepatan cahaya", "bandwidth",
            "core", "cladding", "pantulan internal", "foton"
        ),
        capabilities=("hero_subject", "detail_zoom", "process_node"),
        composable_with=("subseaCableCutaway", "serverRack", "cloudArch"),
        preferred_environments=("oceanFloor", "circuit", "abstract"),
    ),
    "satellite": AssetDescriptor(
        kind="satellite",
        label="Satelit",
        category="space",
        semantic_tags=(
            "satelit", "satellite", "orbit", "angkasa", "luar angkasa", "space", "starlink",
            "pemancar", "transceiver", "panel surya", "komunikasi antariksa", "gps", "sinyal radio"
        ),
        capabilities=("hero_subject", "scale_comparison", "process_node"),
        composable_with=("planetEarth", "antenna", "rocket"),
        preferred_environments=("space", "abstract"),
    ),
    "antenna": AssetDescriptor(
        kind="antenna",
        label="Menara Sinyal",
        category="infrastructure",
        semantic_tags=(
            "antena", "antenna", "tower", "menara", "bts", "sinyal", "radio", "frekuensi",
            "gelombang", "nirkabel", "wireless", "5g", "4g", "telekomunikasi", "seluler"
        ),
        capabilities=("hero_subject", "process_node"),
        composable_with=("phone", "satellite", "building"),
        preferred_environments=("city", "abstract", "grid"),
    ),

    # Computing, Chips & Cloud Infrastructure
    "gpu": AssetDescriptor(
        kind="gpu",
        label="GPU",
        category="computing",
        semantic_tags=(
            "gpu", "graphics card", "nvidia", "cuda", "vram", "akselerator", "ai compute",
            "tensor", "floating point", "chip", "kartu grafis", "parallel compute", "render"
        ),
        capabilities=("hero_subject", "process_node", "comparison"),
        composable_with=("wafer", "coolingFan", "neuralNet", "serverRack"),
        preferred_environments=("circuit", "dataCenter", "abstract"),
    ),
    "cpuProcessor": AssetDescriptor(
        kind="cpuProcessor",
        label="CPU Processor",
        category="computing",
        semantic_tags=(
            "cpu", "processor", "prosesor", "core", "intel", "amd", "silicon", "logic gate",
            "instruksi", "clock speed", "ghz", "komputasi", "arithmetic", "microchip"
        ),
        capabilities=("hero_subject", "process_node", "comparison"),
        composable_with=("wafer", "coolingFan", "meshTopology"),
        preferred_environments=("circuit", "dataCenter", "abstract"),
    ),
    "wafer": AssetDescriptor(
        kind="wafer",
        label="Silicon Wafer",
        category="computing",
        semantic_tags=(
            "wafer", "silikon", "silicon", "fab", "tsmc", "semikonduktor", "litografi",
            "nanometer", "die", "fotolitografi", "asml", "fabrikasi", "piringan"
        ),
        capabilities=("hero_subject", "detail_zoom", "scale_comparison"),
        composable_with=("gpu", "cpuProcessor"),
        preferred_environments=("circuit", "lab", "abstract"),
    ),
    "serverRack": AssetDescriptor(
        kind="serverRack",
        label="Server Rack",
        category="computing",
        semantic_tags=(
            "server", "rack", "rak server", "data", "hosting", "storage", "enterprise",
            "backend", "sysadmin", "infrastruktur", "node", "kluster"
        ),
        capabilities=("hero_subject", "process_node"),
        composable_with=("dataCenter", "coolingFan", "database"),
        preferred_environments=("dataCenter", "abstract"),
    ),
    "dataCenter": AssetDescriptor(
        kind="dataCenter",
        label="Data Center",
        category="computing",
        semantic_tags=(
            "data center", "pusat data", "fasilitas", "server room", "hyperscale",
            "gedung server", "cloud facility", "infrastruktur awan", "colocation"
        ),
        capabilities=("hero_subject", "scale_comparison"),
        composable_with=("serverRack", "cloudArch", "coolingFan"),
        preferred_environments=("dataCenter", "city", "abstract"),
    ),
    "cloudArch": AssetDescriptor(
        kind="cloudArch",
        label="Cloud Architecture",
        category="computing",
        semantic_tags=(
            "cloud", "awan", "arsitektur", "microservice", "load balancer", "api gateway",
            "distributed", "aws", "gcp", "azure", "serverless", "skalabilitas", "cluster"
        ),
        capabilities=("hero_subject", "process_node"),
        composable_with=("serverRack", "database", "neuralNet"),
        preferred_environments=("grid", "abstract", "dataCenter"),
    ),
    "neuralNet": AssetDescriptor(
        kind="neuralNet",
        label="Neural Network",
        category="computing",
        semantic_tags=(
            "neural network", "jaringan saraf", "ai", "artificial intelligence", "deep learning",
            "machine learning", "model", "bobot", "layer", "synapse", "llm", "transformer"
        ),
        capabilities=("hero_subject", "process_node", "comparison"),
        composable_with=("gpu", "database", "cloudArch"),
        preferred_environments=("circuit", "abstract", "grid"),
    ),
    "database": AssetDescriptor(
        kind="database",
        label="Database",
        category="computing",
        semantic_tags=(
            "database", "basis data", "sql", "nosql", "penyimpanan", "tabel", "query",
            "relasional", "acid", "index", "arsip data", "rekaman"
        ),
        capabilities=("hero_subject", "process_node"),
        composable_with=("serverRack", "cloudArch"),
        preferred_environments=("dataCenter", "abstract"),
    ),
    "quantumProcessor": AssetDescriptor(
        kind="quantumProcessor",
        label="Quantum Processor",
        category="computing",
        semantic_tags=(
            "quantum", "kuantum", "qubit", "superkonduktor", "superposisi", "entanglement",
            "komputasi kuantum", "cryogenic", "pendingin mutlak", "quantum supremacy"
        ),
        capabilities=("hero_subject", "detail_zoom"),
        composable_with=("wafer", "coolingFan"),
        preferred_environments=("lab", "abstract", "circuit"),
    ),

    # Astronomy, Nature & Space
    "planetEarth": AssetDescriptor(
        kind="planetEarth",
        label="Planet Bumi",
        category="space",
        semantic_tags=(
            "bumi", "earth", "planet", "globe", "dunia", "antarbenua", "samudra",
            "atmosfer", "geografi", "kehidupan", "benua", "luar angkasa", "astronomi", "tata surya"
        ),
        capabilities=("hero_subject", "scale_comparison"),
        composable_with=("satellite", "rocket"),
        preferred_environments=("space", "abstract"),
    ),
    "rocket": AssetDescriptor(
        kind="rocket",
        label="Roket",
        category="space",
        semantic_tags=(
            "roket", "rocket", "peluncuran", "launch", "spacecraft", "pesawat luar angkasa",
            "propulsi", "orbit", "antariksa", "eksplorasi", "bahan bakar"
        ),
        capabilities=("hero_subject", "scale_comparison"),
        composable_with=("satellite", "planetEarth"),
        preferred_environments=("space", "abstract"),
    ),

    # Everyday Science, Food & Lifestyle
    "ramenBowl": AssetDescriptor(
        kind="ramenBowl",
        label="Mangkok Mi",
        category="lifestyle",
        semantic_tags=(
            "mi", "mie", "ramen", "noodle", "makanan", "pangan", "nutrisi", "karbohidrat",
            "natrium", "garam", "kuah", "telur", "nori", "sarapan", "makan siang", "instan"
        ),
        capabilities=("hero_subject", "detail_zoom", "comparison"),
        composable_with=("cookingPot",),
        preferred_environments=("kitchen", "abstract"),
    ),
    "cookingPot": AssetDescriptor(
        kind="cookingPot",
        label="Panci Masak",
        category="lifestyle",
        semantic_tags=(
            "panci", "pot", "masak", "memasak", "rebus", "mendidih", "air mendidih", "kompor",
            "uap", "dapur", "panas", "titik didih", "termal", "makanan"
        ),
        capabilities=("hero_subject", "process_node"),
        composable_with=("ramenBowl",),
        preferred_environments=("kitchen", "abstract"),
    ),

    # Everyday Technology, Devices & Gadgets
    "phone": AssetDescriptor(
        kind="phone",
        label="Ponsel",
        category="lifestyle",
        semantic_tags=(
            "ponsel", "hp", "smartphone", "handphone", "aplikasi", "layar", "user",
            "pengguna", "mobile", "gadget", "notifikasi", "touchscreen", "komunikasi"
        ),
        capabilities=("hero_subject", "process_node"),
        composable_with=("antenna", "satellite", "dataCenter"),
        preferred_environments=("city", "abstract"),
    ),
    "drone": AssetDescriptor(
        kind="drone",
        label="Drone",
        category="infrastructure",
        semantic_tags=(
            "drone", "quadcopter", "uav", "terbang", "baling-baling", "kamera udara",
            "sensor", "surveillance", "otonom", "kendali jarak jauh"
        ),
        capabilities=("hero_subject",),
        composable_with=("antenna", "phone"),
        preferred_environments=("city", "grid", "abstract"),
    ),

    # Energy, Industry & Power
    "solarPanel": AssetDescriptor(
        kind="solarPanel",
        label="Panel Surya",
        category="energy",
        semantic_tags=(
            "surya", "matahari", "solar", "panel", "fotovoltaik", "energi terbarukan",
            "listrik", "daya", "sel surya", "ramah lingkungan", "sumber daya"
        ),
        capabilities=("hero_subject", "process_node"),
        composable_with=("turbine", "coolingFan"),
        preferred_environments=("abstract", "grid", "city"),
    ),
    "turbine": AssetDescriptor(
        kind="turbine",
        label="Turbin",
        category="energy",
        semantic_tags=(
            "turbin", "angin", "kincir", "generator", "pembangkit", "listrik", "daya",
            "rotor", "putaran", "mekanik", "energi bersih"
        ),
        capabilities=("hero_subject", "process_node"),
        composable_with=("solarPanel", "coolingFan"),
        preferred_environments=("abstract", "grid"),
    ),
    "coolingFan": AssetDescriptor(
        kind="coolingFan",
        label="Pendingin",
        category="energy",
        semantic_tags=(
            "kipas", "pendingin", "fan", "cooling", "ventilasi", "suhu", "panas",
            "disipasi panas", "aliran udara", "heatsink"
        ),
        capabilities=("process_node", "comparison"),
        composable_with=("gpu", "serverRack", "cpuProcessor"),
        preferred_environments=("dataCenter", "circuit", "abstract"),
    ),

    # Business, Architecture & 3D Concepts
    "building": AssetDescriptor(
        kind="building",
        label="Kantor",
        category="business",
        semantic_tags=(
            "gedung", "kantor", "perusahaan", "korporasi", "bisnis", "kantor pusat",
            "markas", "bangunan", "arsitektur kota", "industri", "skyscrapers"
        ),
        capabilities=("hero_subject", "scale_comparison"),
        composable_with=("dataCenter", "phone"),
        preferred_environments=("city", "abstract"),
    ),
    "meshTopology": AssetDescriptor(
        kind="meshTopology",
        label="Mesh 3D",
        category="graphics",
        semantic_tags=(
            "mesh", "wireframe", "poligon", "topologi", "edge loop", "model 3d",
            "geometri", "render 3d", "vertex", "grafika komputer", "blender"
        ),
        capabilities=("hero_subject", "detail_zoom"),
        composable_with=("claySculpt", "gpu"),
        preferred_environments=("abstract", "circuit"),
    ),
    "claySculpt": AssetDescriptor(
        kind="claySculpt",
        label="Clay Sculpt",
        category="graphics",
        semantic_tags=(
            "clay", "sculpt", "pahat", "patung", "volume", "karakter", "organik",
            "modeling organik", "zbrush", "seni digital"
        ),
        capabilities=("hero_subject", "comparison"),
        composable_with=("meshTopology",),
        preferred_environments=("abstract", "lab"),
    ),
    "microscope": AssetDescriptor(
        kind="microscope",
        label="Mikroskop Sains",
        category="science",
        semantic_tags=(
            "mikroskop", "microscope", "sel", "bakteri", "virus", "molekul", "optik", "lensa",
            "laboratorium", "penelitian", "sains", "biologi", "mikro", "medis", "sampel", "preparat"
        ),
        capabilities=("hero_subject", "detail_zoom"),
        composable_with=("lightBulb", "cookingPot"),
        preferred_environments=("lab", "abstract"),
    ),
    "lightBulb": AssetDescriptor(
        kind="lightBulb",
        label="Bohlam Inovasi",
        category="science",
        semantic_tags=(
            "bohlam", "lampu", "lightbulb", "bulb", "ide", "inovasi", "penemuan", "listrik",
            "edison", "filamen", "tungsten", "cahaya", "energi", "konsep", "kreativitas"
        ),
        capabilities=("hero_subject", "comparison"),
        composable_with=("microscope", "factory", "cpuProcessor"),
        preferred_environments=("lab", "abstract", "circuit"),
    ),
    "factory": AssetDescriptor(
        kind="factory",
        label="Pabrik Industri",
        category="business",
        semantic_tags=(
            "pabrik", "factory", "manufaktur", "industri", "produksi", "revolusi industri",
            "cerobong", "asap", "mesin", "assembly line", "perakitan", "skala besar", "supply chain"
        ),
        capabilities=("hero_subject", "scale_comparison"),
        composable_with=("building", "stockChart", "turbine"),
        preferred_environments=("city", "grid", "abstract"),
    ),
    "stockChart": AssetDescriptor(
        kind="stockChart",
        label="Grafik Pasar / Tren",
        category="business",
        semantic_tags=(
            "saham", "grafik", "chart", "pasar", "ekonomi", "bisnis", "keuangan", "tren",
            "valuasi", "finansial", "growth", "pertumbuhan", "metrik", "data", "investasi"
        ),
        capabilities=("hero_subject", "scale_comparison"),
        composable_with=("building", "factory", "database"),
        preferred_environments=("city", "abstract", "grid"),
    ),
}


class AssetResolver:
    """Deterministic asset resolution matching semantic queries to shipped vector assets."""

    @classmethod
    def resolve_object(cls, query: str, context: str = "") -> str | None:
        """Find the best matching ObjectKind using semantic tag overlap and term scoring."""
        cleaned = re.sub(r"[^\w\s]", " ", f"{query} {context}".lower())
        tokens = set(cleaned.split())

        # 1. Exact canonical name match
        for kind in OBJECT_KINDS:
            if kind.lower() in tokens or kind.lower() == query.strip().lower():
                return kind

        # 2. Semantic tag scoring
        best_kind: str | None = None
        best_score = 0

        for kind, desc in ASSET_DESCRIPTORS.items():
            score = 0
            # Check for exact multi-word tag matches first (e.g. "serat optik", "kabel bawah laut")
            text_str = f" {cleaned} "
            for tag in desc.semantic_tags:
                if f" {tag} " in text_str:
                    # Multi-word tag match scores higher
                    score += 5 if " " in tag else 2
                elif any(tok == tag for tok in tokens):
                    score += 2

            if score > best_score:
                best_score = score
                best_kind = kind

        # Minimum confidence threshold (at least one exact keyword or phrase match)
        if best_score >= 2:
            return best_kind
        return None

    @classmethod
    def resolve_environment(cls, query: str, context: str = "") -> str:
        """Resolve suitable environment backdrop based on narrative context."""
        text = f"{query} {context}".lower()
        if any(w in text for w in ("dasar laut", "laut", "samudra", "ocean", "bawah laut", "trench", "underwater")):
            return "oceanFloor"
        if any(w in text for w in ("dapur", "masak", "panci", "rebus", "makanan", "kitchen", "cooking", "ramen", "mi")):
            return "kitchen"
        if any(w in text for w in ("angkasa", "luar angkasa", "orbit", "planet", "bintang", "satelit", "space", "galaksi")):
            return "space"
        if any(w in text for w in ("server", "data center", "rak server", "fasilitas server", "pusat data")):
            return "dataCenter"
        if any(w in text for w in ("chip", "silikon", "prosesor", "semikonduktor", "wafer", "gpu", "circuit", "sirkuit")):
            return "circuit"
        if any(w in text for w in ("lab", "laboratorium", "penelitian", "eksperimen", "qubit", "kuantum")):
            return "lab"
        if any(w in text for w in ("kota", "gedung", "perusahaan", "kantor", "city", "urban")):
            return "city"
        if any(w in text for w in ("jaringan", "arsitektur", "cloud", "grid", "network", "distributed")):
            return "grid"
        return "abstract"

    @classmethod
    def resolve_visual_plan(
        cls,
        visual_plan: dict[str, Any],
        script: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Convert a SemanticVisualPlan into a concrete resolved asset manifest and missing reports.

        Returns (assets_payload, missing_reports).
        """
        beats = visual_plan.get("beats") or []
        resolved_objects: dict[str, dict[str, Any]] = {}
        resolved_environments: set[str] = set()
        missing_reports: list[dict[str, Any]] = []

        raw_segments = script.get("segments") if isinstance(script, dict) else []
        segments_list = raw_segments if isinstance(raw_segments, list) else []
        script_segments = {
            str(s["id"]): str(s.get("text", ""))
            for s in segments_list
            if isinstance(s, dict) and "id" in s
        }

        for beat in beats:
            if not isinstance(beat, dict):
                continue
            seg_id = str(beat.get("narrationSegmentId") or "")
            seg_text = script_segments.get(seg_id, "")
            concept = str(beat.get("conceptToExplain") or "")
            subjects = beat.get("primarySubjects") or []
            required_objs = beat.get("requiredObjects") or []

            all_queries = list(subjects) + list(required_objs)
            beat_resolved_kinds: list[str] = []

            for query in all_queries:
                matched_kind = cls.resolve_object(query, context=f"{concept} {seg_text}")
                if matched_kind and matched_kind in OBJECT_KINDS:
                    beat_resolved_kinds.append(matched_kind)
                    if matched_kind not in resolved_objects:
                        desc = ASSET_DESCRIPTORS.get(matched_kind)
                        resolved_objects[matched_kind] = {
                            "kind": matched_kind,
                            "label": desc.label if desc else OBJECT_LABELS.get(matched_kind, matched_kind),
                            "category": desc.category if desc else "general",
                            "source": desc.source if desc else "packages/video/src/art/objects.tsx",
                            "license": desc.license if desc else "project-original",
                            "capabilities": list(desc.capabilities) if desc else ["hero_subject"],
                        }

            # Environment resolution
            env = str(beat.get("environment") or "")
            if env not in ENVIRONMENTS:
                env = cls.resolve_environment(env, context=f"{concept} {seg_text}")
            resolved_environments.add(env)

            # Verification: if a beat has required subjects but ZERO resolved objects
            if all_queries and not beat_resolved_kinds:
                # Missing mandatory asset
                missing_reports.append({
                    "segment": seg_id,
                    "concept": concept,
                    "requested": all_queries,
                    "reason": f"No shipped SVG component matches requested subjects {all_queries}",
                })

        # Base payload shape
        assets_payload = {
            "schema_version": 1,
            "objects": list(resolved_objects.values()),
            "environments": sorted(resolved_environments),
            "missing": missing_reports,
        }

        return assets_payload, missing_reports
