import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

PROGRAM_KEY = "INGENIERÍA EN COMPUTACIÓN_1997"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_tipo(value: str) -> str:
    value = (value or "").strip().lower()
    if value in {"curso", "course", "cource"}:
        return "course"
    if value in {"examen", "exam", "ex"}:
        return "exam"
    return value


def read_approved(csv_path: Path) -> Tuple[Set[str], Set[str]]:
    approved_courses: Set[str] = set()
    approved_exams: Set[str] = set()

    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        # Accept flexible header casing.
        field_map = {name.lower(): name for name in reader.fieldnames or []}
        tipo_key = field_map.get("tipo")
        codigo_key = field_map.get("codigo")
        if not tipo_key or not codigo_key:
            raise ValueError("CSV must contain headers 'tipo' and 'codigo'")

        for row in reader:
            tipo = normalize_tipo(row.get(tipo_key, ""))
            codigo = (row.get(codigo_key) or "").strip()
            if not codigo:
                continue
            if tipo == "exam":
                approved_exams.add(codigo)
            else:
                approved_courses.add(codigo)

    return approved_courses, approved_exams


def build_credits_index(credits_prog: Dict[str, Any]) -> Dict[str, int]:
    index: Dict[str, int] = {}
    for entry in credits_prog.values():
        code = entry.get("codigo")
        if not code:
            continue
        try:
            index[code] = int(entry.get("creditos", 0))
        except (TypeError, ValueError):
            index[code] = 0
    return index


def total_credits(
    approved_codes: Iterable[str], credits_by_code: Dict[str, int], override: int | None
) -> int:
    if override is not None:
        return override
    total = 0
    for code in set(approved_codes):
        total += credits_by_code.get(code, 0)
    return total


def requirement_satisfied(node: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    node_type = node.get("type")
    if node_type == "ALL":
        return all(requirement_satisfied(child, ctx) for child in node.get("children", []))
    if node_type == "ANY":
        children = node.get("children", [])
        return any(requirement_satisfied(child, ctx) for child in children) if children else False
    if node_type == "NOT":
        return not any(requirement_satisfied(child, ctx) for child in node.get("children", []))
    if node_type == "LEAF":
        items = node.get("items", [])
        required_raw = node.get("required_count")
        required = required_raw if required_raw is not None else len(items)
        matched = 0
        for item in items:
            modality = item.get("modality")
            code = item.get("code", "")
            if modality in {"course", "ucb_module"}:
                if code in ctx["approved_courses"] or code in ctx["approved_exams"]:
                    matched += 1
            elif modality == "exam":
                if code in ctx["approved_exams"] or code in ctx["approved_courses"]:
                    matched += 1
            elif modality == "credits_in_plan":
                needed = item.get("credits_required", 0)
                if ctx["total_credits"] >= needed:
                    matched += 1
        return matched >= required
    # Unknown node types are treated as unsatisfied.
    return False


def evaluate_previas(requirements: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    if not requirements:
        return True
    return requirement_satisfied(requirements, ctx)


def find_eligible(
    previas_prog: Dict[str, Any],
    vigentes_prog: Dict[str, Any],
    credits_by_code: Dict[str, int],
    approved_courses: Set[str],
    approved_exams: Set[str],
    credits_override: int | None,
) -> List[Dict[str, Any]]:
    previas_codes = {
        entry.get("code") for entry in previas_prog.values() if entry.get("code")
    }
    ctx = {
        "approved_courses": approved_courses,
        "approved_exams": approved_exams,
        "total_credits": total_credits(
            approved_courses | approved_exams, credits_by_code, credits_override
        ),
    }

    eligible: List[Dict[str, Any]] = []
    for entry in previas_prog.values():
        code = entry.get("code")
        if not code:
            continue
        # Skip items already approved.
        if code in ctx["approved_courses"] or code in ctx["approved_exams"]:
            continue

        requirements = entry.get("requirements")
        if not evaluate_previas(requirements, ctx):
            continue

        meta = vigentes_prog.get(code, {})
        if meta.get("university_code") == None:
            continue
        tipo_val = normalize_tipo(entry.get("type_previas", ""))
        eligible.append(
            {
                "codigo": code,
                "nombre": entry.get("name", ""),
                "type": tipo_val,
                "university_code": meta.get("university_code", ""),
                "credits": credits_by_code.get(code, ""),
            }
        )
    existing_codes = {row["codigo"] for row in eligible}
    for code, meta in vigentes_prog.items():
        if not code or code in existing_codes or code in previas_codes:
            continue
        if code in ctx["approved_courses"] or code in ctx["approved_exams"]:
            continue
        if meta.get("university_code") is None:
            continue
        eligible.append(
            {
                "codigo": code,
                "nombre": meta.get("course_name", ""),
                "type": "",
                "university_code": meta.get("university_code", ""),
                "credits": credits_by_code.get(code, ""),
            }
        )
    return sorted(eligible, key=lambda x: x["codigo"])


def write_output(rows: List[Dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["codigo", "nombre", "type", "university_code", "credits"],
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List courses/exams you can take for INGENIERÍA EN COMPUTACIÓN_1997."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("approved.csv"),
        help="CSV with headers 'tipo','codigo' for already-approved items.",
    )
    parser.add_argument(
        "--previas",
        type=Path,
        default=Path("data/previas_data_backup.json"),
        help="Path to previas JSON.",
    )
    parser.add_argument(
        "--vigentes",
        type=Path,
        default=Path("data/vigentes_data_backup.json"),
        help="Path to vigentes JSON.",
    )
    parser.add_argument(
        "--credits",
        type=Path,
        default=Path("data/credits_data_backup.json"),
        help="Path to credits JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eligible_output.csv"),
        help="Output CSV path.",
    )
    parser.add_argument(
        "--credits-earned",
        type=int,
        default=None,
        help="Override total earned credits (otherwise inferred from approved list).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    previas_data = load_json(args.previas).get(PROGRAM_KEY, {})
    vigentes_data = load_json(args.vigentes).get(PROGRAM_KEY, {})
    credits_data = load_json(args.credits).get(PROGRAM_KEY, {})

    approved_courses, approved_exams = read_approved(args.input)
    credits_by_code = build_credits_index(credits_data)

    eligible = find_eligible(
        previas_prog=previas_data,
        vigentes_prog=vigentes_data,
        credits_by_code=credits_by_code,
        approved_courses=approved_courses,
        approved_exams=approved_exams,
        credits_override=args.credits_earned,
    )

    write_output(eligible, args.output)
    print(f"Eligible items: {len(eligible)}")
    print(f"Total credits considered: {total_credits(approved_courses | approved_exams, credits_by_code, args.credits_earned)}")
    print(f"Written to: {args.output}")


if __name__ == "__main__":
    main()

