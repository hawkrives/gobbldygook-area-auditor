from typing import Iterator, Dict, cast
import json
import csv
import sys

import yaml

from .area import AreaOfStudy
from .exception import load_exception, CourseOverrideException
from .grades import grade_point_average_items, grade_point_average
from .data.student import Student
from .audit import audit, Message, Arguments


def run(args: Arguments, *, student: Dict, area_spec: Dict) -> Iterator[Message]:
    area_code = area_spec['code']

    credit_assignments = area_spec.get('credit', {})

    exceptions = [
        load_exception(e)
        for e in student.get("exceptions", [])
        if e['area_code'] == area_code
    ]
    course_overrides = [e for e in exceptions if isinstance(e, CourseOverrideException)]

    loaded = Student.load(student, code=area_code, overrides=course_overrides, credits_overrides=credit_assignments)

    if args.transcript_only:
        writer = csv.writer(sys.stdout)
        writer.writerow(['course', 'name', 'clbid', 'type', 'credits', 'term', 'type', 'grade', 'in_gpa'])
        for c in loaded.courses:
            writer.writerow([
                c.course(), c.name, c.clbid, c.course_type.value, str(c.credits), f"{c.year}-{c.term}",
                c.sub_type.name, c.grade_code.value, 'Y' if c.is_in_gpa else 'N',
            ])
        return

    if args.gpa_only:
        writer = csv.writer(sys.stdout)
        writer.writerow(['course', 'grade', 'points'])

        applicable = sorted(grade_point_average_items(loaded.courses_with_failed), key=lambda c: (c.year, c.term, c.course(), c.clbid))
        for c in applicable:
            writer.writerow([c.course(), c.grade_code.value, str(c.grade_points)])

        writer.writerow(['---', 'gpa:', str(grade_point_average(loaded.courses_with_failed))])
        return

    area = AreaOfStudy.load(
        specification=area_spec,
        c=loaded.constants(),
        student=loaded,
        exceptions=exceptions,
    )
    area.validate()

    yield from audit(
        area=area,
        student=loaded,
        exceptions=exceptions,
        args=args,
    )


def load_student(filename: str) -> Dict:
    with open(filename, "r", encoding="utf-8") as infile:
        return cast(Dict, json.load(infile))


def load_area(filename: str) -> Dict:
    with open(filename, "r", encoding="utf-8") as infile:
        return cast(Dict, yaml.load(stream=infile, Loader=yaml.SafeLoader))
