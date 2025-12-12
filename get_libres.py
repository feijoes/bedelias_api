#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import csv
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================

# Change this to the path of your JSON file
JSON_PATH = Path("data/previas_data_backup.json")
"INGENIERÍA QUÍMICA_2021"
carrera = "INGENIERÍA EN COMPUTACIÓN_1997"

# ============================================================
# Helpers to detect "the same course"
# ============================================================

def normalize_title(s: str) -> str:
    """Normalize titles to compare them safely (lowercase, trim, collapse spaces)."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def is_same_course_item(item: dict, exam_code: str, exam_name: str) -> bool:
    """
    Returns True if this item represents *the same course* as the exam.

    This covers:
      - same code (e.g. exam code 1650 and course code 1650)
      - OR a different code but *same name/title* as the exam (e.g. 1610 vs 1650
        both named "INT. A LA INVESTIGACION DE OPERACIONES")
      - OR same code and name in title format "CODE - NAME"

    Only items with modality "course" or "ucb_module" are treated as "the course".
    """
    modality = item.get("modality")

    if modality not in ("course", "ucb_module"):
        return False

    item_code = item.get("code", "")
    item_title = item.get("title", "")

    # 1) Exact same code
    if item_code == exam_code:
        return True

    # 2) Different code but same name (for old/new codes equivalents like 1610/1650)
    if normalize_title(item_title) == normalize_title(exam_name):
        return True

    # 3) Title matches the expected format "CODE - NAME" for this exam
    expected_title = f"{exam_code} - {exam_name}"
    if normalize_title(item_title) == normalize_title(expected_title):
        return True

    return False


# ============================================================
# Core recursive evaluation
# ============================================================

def can_satisfy_without_course(node: dict, exam_code: str, exam_name: str) -> bool:
    """
    Returns True if this requirements subtree can be satisfied
    without *ever* using "the course" (exam_code/exam_name equivalents).

    We are not checking a real student's record here, just whether
    a satisfying assignment exists that doesn't use the course.
    """
    node_type = (node.get("type") or "").upper()

    # ----------------- LEAF -----------------
    if node_type == "LEAF":
        items = node.get("items", [])
        required_count = node.get("required_count", len(items))

        # keep only items that are NOT considered the same course
        non_course_items = [
            it for it in items
            if not is_same_course_item(it, exam_code, exam_name)
        ]

        return len(non_course_items) >= required_count

    # ----------------- ALL ------------------
    elif node_type == "ALL":
        children = node.get("children", [])
        return all(
            can_satisfy_without_course(child, exam_code, exam_name)
            for child in children
        )

    # ----------------- ANY ------------------
    elif node_type == "ANY":
        children = node.get("children", [])
        return any(
            can_satisfy_without_course(child, exam_code, exam_name)
            for child in children
        )

    # ----------------- NOT ------------------
    elif node_type == "NOT":
        # "NOT" means you must NOT have the items inside.
        # There is always an assignment where we simply "don't have them",
        # so from an existence point of view this is always satisfiable
        # without needing the course.
        return True

    # --------------- UNKNOWN ----------------
    else:
        # Be conservative: unknown node types -> treat as unsatisfiable
        return False


# ============================================================
# Main search
# ============================================================

def get_credits_for_course(course_code, credits_data):
    """Get credits for a course code from credits data."""
    for cred_key, cred_course in credits_data.items():
        if cred_course.get('codigo') == course_code:
            return cred_course.get('creditos', 'N/A')
    return 'N/A'

def main():
    # Load JSON
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)[carrera]

    with open("data/vigentes_data_backup.json", "r", encoding="utf-8") as f:
        vigentes = json.load(f)[carrera]

    with open("data/credits_data_backup.json", "r", encoding="utf-8") as f:
        credits_data = json.load(f)[carrera]

    exams_that_dont_require_course = []
    exams_can_without_course = []
    calidad_libre_courses = []

    for key, course in data.items():
        if course.get("type_previas") != "Examen":
            continue  # only look at exam-type entries

        exam_code = course.get("code", "")
        exam_name = course.get("name", "")
        requirements = course.get("requirements")

        vigentes_course = vigentes.get(exam_code)
        if not vigentes_course or "CIM" in exam_code or vigentes_course.get("university_code") == "CENURLN":
            continue
        course['university_code'] = vigentes_course.get("university_code")
        course['credits'] = get_credits_for_course(exam_code, credits_data)
        # No requirements at all → definitely can be done without the course
        if not requirements:
            exams_can_without_course.append(course)
            continue

        if can_satisfy_without_course(requirements, exam_code, exam_name):
            exams_can_without_course.append(course)

    # Find courses that are in vigentes & credits but NOT in previas (calidad libre)
    previas_codes = {course.get("code") for course in data.values()}
    for vig_code, vig_course in vigentes.items():
        # Skip if already in previas
        if vig_code in previas_codes:
            continue

        # Check if exists in credits
        credits_exists = any(cred_course.get('codigo') == vig_code for cred_course in credits_data.values())

        if credits_exists:
            calidad_libre_courses.append({
                'code': vig_code,
                'name': vig_course.get('course_name', ''),
                'university_code': vig_course.get('university_code', ''),
                'credits': get_credits_for_course(vig_code, credits_data),
                'source': 'calidad_libre'
            })


    # Filter out exams from CENURLN, CURE, and CUT universities
    excluded_universities = {"CENURLN", "CURE", "CUT"}

    exams_can_without_course_filtered = [
        c for c in exams_can_without_course
        if c.get('university_code') not in excluded_universities
    ]

    calidad_libre_filtered = [
        c for c in calidad_libre_courses
        if c.get('university_code') not in excluded_universities
    ]

    # ---------------- Output ----------------
    print("======================================================")
    print("ALL LIBRE COURSES (can be taken without prerequisites)")
    print("Exams without course + Calidad Libre courses")
    print("Filtered: excluding CENURLN, CURE, and CUT universities")
    print("Format: CREDITS - CODE - NAME - UNIVERSITY")
    print("======================================================")

    # Combine all libre courses
    all_libre_courses = exams_can_without_course_filtered + calidad_libre_filtered

    # Sort by credits (descending) then by name
    def sort_key(course):
        credits = course.get('credits', '0')
        try:
            return (int(credits), course.get('name', ''))
        except ValueError:
            return (0, course.get('name', ''))

    all_libre_courses.sort(key=sort_key, reverse=True)

    # Print to console
    for c in all_libre_courses:
        credits = c.get('credits', 'N/A')
        code = c.get('code', '')
        name = c.get('name', '')
        university = c.get('university_code', '')
        print(f"{credits} - {code} - {name} - {university}")

    # Save to CSV
    csv_filename = "libre_courses.csv"
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['credits', 'code', 'name', 'university_code', 'source']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for c in all_libre_courses:
            writer.writerow({
                'credits': c.get('credits', 'N/A'),
                'code': c.get('code', ''),
                'name': c.get('name', ''),
                'university_code': c.get('university_code', ''),
                'source': c.get('source', 'exam')
            })

    print(f"\nCSV file saved as: {csv_filename}")

    print("\nSummary (filtered data):")
    print(f"  Libre courses total         : {len(all_libre_courses)}")
    print(f"    - Exams without course    : {len(exams_can_without_course_filtered)}")
    print(f"    - Calidad libre courses   : {len(calidad_libre_filtered)}")
    print(f"\nFiltered out {len(exams_can_without_course) - len(exams_can_without_course_filtered)} exams without course and {len(calidad_libre_courses) - len(calidad_libre_filtered)} calidad libre courses from CENURLN/CURE/CUT")






if __name__ == "__main__":
    main()