#!/usr/bin/env python3
"""Внешняя приёмка статического стенда: только HTTP и стандартная библиотека."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import sys
import urllib.error
import urllib.request

EXPECTED = {
    "alien_topology_059": {"objects": 3, "triangles": 16224, "preview_nodes": 2},
    "saddle_bracket_photo": {"objects": 1, "triangles": 413310, "preview_nodes": 1},
    "bottle_styles_058": {"objects": 5, "triangles": 156008, "preview_nodes": 5},
    "petaloid_bottom_058": {"objects": 1, "triangles": 36720, "preview_nodes": 1},
    "jar_styles_058": {"objects": 3, "triangles": 82650, "preview_nodes": 3},
    "living_room_058": {"objects": 238, "triangles": 140168, "preview_nodes": 238},
    "train_carriage_058": {"objects": 1186, "triangles": 336784, "preview_nodes": 140},
    "track_holes_057": {"objects": 1, "triangles": 1236, "preview_nodes": 1},
    "lightning_057": {"objects": 1, "triangles": 7232, "preview_nodes": 1},
    "bicycle_chain_057": {"objects": 58, "triangles": 28840, "preview_nodes": 4},
    "jar_057": {"objects": 2, "triangles": 29744, "preview_nodes": 2},
    "bottle_057": {"objects": 4, "triangles": 63820, "preview_nodes": 4},
    "lids_057": {"objects": 8, "triangles": 14076, "preview_nodes": 5},
    "switch_057": {"objects": 9, "triangles": 3158, "preview_nodes": 3},
    "train_carriage": {"objects": 1186, "triangles": 336784, "preview_nodes": 140},
    "thinkpad_x1_056": {"objects": 66, "triangles": 76418, "preview_nodes": 38, "full_nodes": 73},
    "architecture_selectable_055": {"objects": 88, "triangles": 49424, "preview_nodes": 4,
                                     "preview_triangles": 17988},
    "handle_rosettes_055": {"objects": 8, "triangles": 94308, "preview_nodes": 4},
    "selection_details_055": {"objects": 16, "triangles": 7328, "preview_nodes": 4},
    "fittings_053": {"objects": 26, "triangles": 116518, "preview_nodes": 6},
    "smooth_transitions_054": {"objects": 3, "triangles": 109280, "preview_nodes": 1,
                                "preview_triangles": 26104},
    "glyphs_expansion_053": {"objects": 7, "triangles": 56950, "preview_nodes": 5},
    "living_room_diorama": {"objects": 238, "triangles": 140168, "preview_nodes": 238},
}


def glb_summary(data: bytes) -> dict[str, int]:
    if len(data) < 28 or data[:4] != b"glTF":
        raise AssertionError("Ответ не является GLB")
    version, total_length = struct.unpack_from("<II", data, 4)
    if version != 2 or total_length != len(data):
        raise AssertionError("Некорректный GLB2 header")
    json_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:
        raise AssertionError("В GLB отсутствует JSON chunk")
    document = json.loads(data[20:20 + json_length])
    triangles = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4:
                continue
            if "indices" in primitive:
                triangles += document["accessors"][primitive["indices"]]["count"] // 3
            else:
                triangles += document["accessors"][primitive["attributes"]["POSITION"]]["count"] // 3
    return {"nodes": len(document.get("nodes", [])), "triangles": triangles}


class Acceptance:
    def __init__(self, base: str, revision: str | None, *, strict_gzip: bool = True):
        self.base = base.rstrip("/")
        self.revision = revision
        self.strict_gzip = strict_gzip
        self.identity_responses: list[str] = []
        self.notices: list[str] = []

    def get(self, path: str, *, compressed: bool = False, timeout: int = 120) -> tuple[bytes, dict, int]:
        headers = {"Accept-Encoding": "gzip", "Cache-Control": "no-cache"} if compressed else {
            "Cache-Control": "no-cache",
        }
        request = urllib.request.Request(self.base + path, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            wire_bytes = len(payload)
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            if response.status != 200:
                raise AssertionError(f"{path}: HTTP {response.status}")
            if compressed and response_headers.get("content-encoding", "").lower() == "gzip":
                payload = gzip.decompress(payload)
            elif compressed:
                if self.strict_gzip:
                    details = {key: response_headers.get(key) for key in
                               ("content-type", "content-length", "cache-control", "via")}
                    raise AssertionError(f"{path}: сервер не вернул precompressed gzip; headers={details}")
                # Некоторые внешние proxy раскодируют большой ответ перед
                # передачей клиенту. Это допустимо только внешней проверкой:
                # production-контейнер выше обязан пройти строгий gzip-тест.
                self.identity_responses.append(path)
            return payload, response_headers, wire_bytes

    def check_asset(self, asset: dict, suffix: str) -> bytes:
        data, headers, wire_bytes = self.get("/" + asset["url"], compressed=True)
        encoding = headers.get("content-encoding", "identity")
        if len(data) != asset["bytes"]:
            raise AssertionError(f"{asset['url']}: размер {len(data)} != {asset['bytes']}")
        digest = hashlib.sha256(data).hexdigest()
        if digest != asset["sha256"]:
            raise AssertionError(f"{asset['url']}: SHA-256 не совпал")
        if not asset["file_name"].endswith(suffix):
            raise AssertionError(f"{asset['file_name']}: неверное расширение")
        self.notices.append(
            f"{asset['file_name']}: {len(data)} B, transport={encoding} {wire_bytes} B, SHA OK"
        )
        return data

    def run(self) -> None:
        suffix = f"?revision={self.revision}" if self.revision else "?acceptance=1"
        health_data, _, _ = self.get("/healthz" + suffix, timeout=30)
        health = json.loads(health_data)
        if health.get("ok") is not True or health.get("mode") != "static-showcase":
            raise AssertionError(f"Некорректный healthz: {health}")
        if self.revision and health.get("revision") != self.revision:
            raise AssertionError(f"Публичный revision {health.get('revision')} != {self.revision}")

        html, _, _ = self.get("/", timeout=30)
        page = html.decode("utf-8")
        if 'id="viewer-dialog"' not in page or "forma-token" in page:
            raise AssertionError("Главная страница не является лёгким статическим стендом")
        catalog_data, _, _ = self.get("/assets/catalog.json", compressed=True, timeout=30)
        catalog = json.loads(catalog_data)
        if catalog.get("mode") != "static-showcase":
            raise AssertionError("Неверный режим каталога")
        if self.revision and catalog.get("revision") != self.revision:
            raise AssertionError("Revision каталога не совпал")
        versions = {version["id"]: version for version in catalog.get("versions", [])}
        if set(versions) != {"0.59", "photo-2026-10", "0.58", "0.57", "train-2026-10", "0.56", "0.55", "0.54", "0.53", "0.52"}:
            raise AssertionError(f"Неожиданный список версий: {sorted(versions)}")

        for version in catalog["versions"]:
            if not version.get("changes") or not version.get("models"):
                raise AssertionError(f"{version['id']}: пустые изменения или модели")
            for change in version["changes"]:
                if change.get("image"):
                    data, _, _ = self.get("/" + change["image"], timeout=30)
                    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
                        raise AssertionError(f"{change['image']}: сравнение не является WebP")
            for model in version["models"]:
                expected = EXPECTED[model["id"]]
                stats = model["stats"]
                for key in ("objects", "triangles"):
                    if stats[key] != expected[key]:
                        raise AssertionError(f"{model['id']}: {key}={stats[key]} != {expected[key]}")
                forma = self.check_asset(model["forma"], ".forma")
                forma.decode("utf-8")
                full = self.check_asset(model["full_glb"], ".glb")
                preview = self.check_asset(model["preview_glb"], ".glb")
                full_summary = glb_summary(full)
                preview_summary = glb_summary(preview)
                full_nodes = expected.get("full_nodes", expected["objects"])
                if full_summary["nodes"] != full_nodes:
                    raise AssertionError(
                        f"{model['id']}: полный GLB nodes={full_summary['nodes']} != {full_nodes}")
                if full_summary["triangles"] != expected["triangles"]:
                    raise AssertionError(f"{model['id']}: неверное число треугольников полного GLB")
                preview_triangles = expected.get("preview_triangles", expected["triangles"])
                if preview_summary != {"nodes": expected["preview_nodes"], "triangles": preview_triangles}:
                    raise AssertionError(f"{model['id']}: preview {preview_summary} != {expected}")
                if stats.get("preview_triangles") != preview_triangles:
                    raise AssertionError(f"{model['id']}: неверный preview_triangles в каталоге")
                if "preview_triangles" in expected and model.get("preview_kind") != "subset":
                    raise AssertionError(f"{model['id']}: облегчённый preview не обозначен как subset")
                for poster in model["posters"]:
                    data, _, _ = self.get("/" + poster["url"], timeout=30)
                    if len(data) != poster["bytes"] or hashlib.sha256(data).hexdigest() != poster["sha256"]:
                        raise AssertionError(f"{poster['url']}: повреждённое превью")
                    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
                        raise AssertionError(f"{poster['url']}: ответ не WebP")
                self.notices.append(
                    f"{model['id']}: full={full_summary}, preview={preview_summary}, posters={len(model['posters'])}"
                )

        request = urllib.request.Request(
            self.base + "/api/build",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code != 410:
                raise AssertionError(f"Editor API вернул HTTP {exc.code}, ожидался 410") from exc
        else:
            raise AssertionError("Editor API не должен существовать на статическом стенде")

        if self.identity_responses:
            print(f"::notice::Proxy returned identity for {len(self.identity_responses)} asset responses; raw bytes and SHA-256 verified")
        for notice in self.notices:
            print(f"::notice::{notice}")
        print(f"::notice::Static showcase OK: {self.base}, revision={health['revision']}, editor API=410")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Например https://forma3d-ratandru.fly.dev")
    parser.add_argument("--revision", help="Обязательный ожидаемый Git SHA")
    parser.add_argument("--allow-proxy-decode", action="store_true",
                        help="Разрешить внешнему proxy вернуть identity после строгой проверки контейнера")
    args = parser.parse_args()
    try:
        Acceptance(args.base, args.revision, strict_gzip=not args.allow_proxy_decode).run()
    except Exception as exc:
        print(f"::error::Showcase acceptance: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
