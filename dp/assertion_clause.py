from typing import Dict, Sequence, Optional, Any, Mapping, List, Union, Tuple, Iterator, cast, TYPE_CHECKING
from collections.abc import Iterable
from decimal import Decimal
import logging
import enum

import attr

from .apply_clause import apply_clause_to_assertion_with_areas, apply_clause_to_assertion_with_data, \
    apply_clause_to_assertion_with_courses, area_actions, course_actions, other_actions, AppliedClauseResult
from .constants import Constants
from .data_type import DataType
from .op import Operator, apply_operator
from .predicate_clause import SomePredicate, load_predicate
from .status import ResultStatus
from .clause_helpers import stringify_expected
from .stringify import str_predicate
from .conditional_expression import load_predicate_expression, SomePredicateExpression
from .data.clausable import Clausable

if TYPE_CHECKING:  # pragma: no cover
    from .context import RequirementContext
    from .data.course import CourseInstance  # noqa: F401
    from .data.area_pointer import AreaPointer  # noqa: F401

logger = logging.getLogger(__name__)
CACHE_SIZE = 2048

ONE_POINT_OH = Decimal(1)
ZERO_POINT_OH = Decimal(0)

SomeAssertion = Union['Assertion', 'ConditionalAssertion']


@enum.unique
class ValueChangeMode(enum.Enum):
    Add = "+"
    Subtract = "-"


@attr.s(frozen=True, cache_hash=True, auto_attribs=True, slots=True, repr=False)
class ValueChange:
    mode: ValueChangeMode
    expression: SomePredicateExpression
    amount: Decimal

    @staticmethod
    def load(
        data: Mapping[str, str],
        *,
        action: str,
        ctx: 'RequirementContext',
    ) -> 'ValueChange':
        predicate_key = load_predicate_expression(data, ctx=ctx)
        predicate_key = predicate_key.evaluate(ctx=ctx)

        cond_action_mode, cond_action_inc = action.split(' ', maxsplit=1)
        mode = ValueChangeMode(cond_action_mode)

        return ValueChange(mode=mode, expression=predicate_key, amount=Decimal(cond_action_inc))


@attr.s(frozen=True, cache_hash=True, auto_attribs=True, slots=True, repr=False)
class Assertion:
    path: Tuple[str, ...]
    state: ResultStatus
    data_type: DataType
    where: Optional[SomePredicate]

    key: str
    operator: Operator
    expected: Decimal
    original: Optional[Union[str, Decimal]]
    changes: Tuple[ValueChange, ...]
    at_most: bool

    # TODO: what is the difference between `message` and `label`?
    message: Optional[str]
    label: Optional[str]
    treat_in_progress_as_pass: bool

    evaluated: bool
    overridden: bool
    resolved: Optional[Decimal] = None
    resolved_items: Optional[Union[Tuple[str, ...], Tuple[Decimal, ...]]] = None
    resolved_clbids: Optional[Tuple[str, ...]] = None
    inserted_clbids: Optional[Tuple[str, ...]] = None

    def validate(self, *, ctx: 'RequirementContext') -> None:
        if self.where:
            self.where.validate(ctx=ctx)

    @staticmethod
    def load(
        data: Dict[str, Any],
        *,
        c: Constants,
        ctx: 'RequirementContext',
        forbid: Sequence[Operator] = tuple(),
        path: List[str],
        data_type: DataType,
    ) -> 'SomeAssertion':
        if not isinstance(data, Mapping):
            raise Exception(f'expected {data} to be a dictionary')

        if "$if" in data:
            return ConditionalAssertion.load(data, path=path, c=c, ctx=ctx, forbid=forbid, data_type=data_type)

        return load_single_assertion(data, path=path, c=c, ctx=ctx, forbid=forbid, data_type=data_type)

    @staticmethod
    def from_args(
        key: str = "???",
        expected: Union[int, Decimal] = 0,
        original: Optional[Union[str, Decimal]] = None,
        operator: Operator = Operator.EqualTo,
        label: Optional[str] = None,
        at_most: bool = False,
        treat_in_progress_as_pass: bool = False,
        state: ResultStatus = ResultStatus.Empty,
    ) -> 'Assertion':
        return Assertion(
            key=key,
            expected=Decimal(expected),
            original=original,
            operator=operator,
            label=label,
            at_most=at_most,
            treat_in_progress_as_pass=treat_in_progress_as_pass,
            state=state,
            changes=tuple(),
            path=tuple(),
            where=None,
            message=None,
            data_type=DataType.Course,
            evaluated=False,
            overridden=False,
            resolved=None,
        )

    def __repr__(self) -> str:
        return f"Assertion({str_predicate(self.to_dict())})"

    def to_dict(self) -> Dict[str, Any]:
        rank, max_rank = self.rank()

        expected = stringify_expected(self.expected)
        original = stringify_expected(self.original)

        as_dict = {
            "type": "assertion",
            "path": list(self.path),
            "status": self.state.value,
            "rank": str(rank),
            "max_rank": str(max_rank),
            "where": self.where.to_dict() if self.where else None,
            "key": self.key,
            "operator": self.operator.name,
            "expected": expected,
            "data-type": self.data_type.value,
            "evaluated": self.evaluated,
            "resolved": str(self.resolved) if self.resolved is not None else None,
            "resolved_items": sorted(stringify_expected(x) for x in self.resolved_items) if self.resolved_items is not None else None,
            "resolved_clbids": sorted(self.resolved_clbids) if self.resolved_clbids is not None else None,
            "inserted_clbids": sorted(self.inserted_clbids) if self.inserted_clbids is not None else None,
        }

        # omit label and message unless they have a set value
        if self.label:
            as_dict["label"] = self.label

        if self.message:
            as_dict["message"] = self.message

        # only insert the original value if it's different from the main one
        if expected != original and original is not None:
            as_dict["original"] = original

        return as_dict

    def waive(self) -> 'Assertion':
        return attr.evolve(
            self,
            resolved=0,
            evaluated=True,
            status=ResultStatus.Waived,
            overridden=True,
        )

    def audit_and_resolve(self, data: Sequence['Clausable'] = tuple(), *, ctx: 'RequirementContext') -> 'SomeAssertion':
        if self.overridden:
            return self

        if self.where:
            filtered_output = [item for item in data if self.where.apply(item)]
        else:
            filtered_output = list(data)

        inserted_clbids = []
        for insert in ctx.get_insert_exceptions(self.path):
            matched_course = ctx.forced_course_by_clbid(insert.clbid, path=self.path)
            logger.debug("inserted %r into assertion (at %s)", matched_course, self.path)
            filtered_output.append(matched_course)
            inserted_clbids.append(matched_course.clbid)

        result_status, calculated_result = self.evaluate(filtered_output)

        return attr.evolve(
            self,
            evaluated=True,
            state=result_status,
            resolved=calculated_result.value,
            resolved_items=calculated_result.data,
            resolved_clbids=tuple(c.clbid for c in calculated_result.courses),
            inserted_clbids=tuple(inserted_clbids),
        )

    def evaluate(self, value: Sequence['Clausable']) -> Tuple[ResultStatus, AppliedClauseResult]:
        if self.data_type is DataType.Course:
            return evaluate_with_courses(self, cast(Sequence['CourseInstance'], value))

        elif self.data_type is DataType.Area:
            return evaluate_with_areas(self, cast(Sequence['AreaPointer'], value))

        elif self.data_type in (DataType.MusicPerformance, DataType.Recital):
            return evaluate_with_items(self, value)

        else:
            raise TypeError(f'unexpected key {self.key!r}')

    def override_expected(self, *, value: Decimal) -> 'Assertion':
        return attr.evolve(self, expected=value, original=str(value))

    def status(self) -> ResultStatus:
        return self.state

    def rank(self) -> Tuple[Decimal, Decimal]:
        global ZERO_POINT_OH, ONE_POINT_OH

        if self.state in (ResultStatus.Done, ResultStatus.Waived):
            return ONE_POINT_OH, ONE_POINT_OH

        assert self.resolved is not None

        if self.operator in (Operator.LessThan, Operator.LessThanOrEqualTo):
            return ZERO_POINT_OH, ONE_POINT_OH

        if self.expected != ZERO_POINT_OH:
            return min(ONE_POINT_OH, self.resolved / self.expected), ONE_POINT_OH

        return ZERO_POINT_OH, ONE_POINT_OH

    def is_simple_count_clause(self) -> bool:
        return self.key in ('count(courses)', 'count(terms)')

    def is_simple_sum_clause(self) -> bool:
        return self.key in ('sum(credits)',)

    def is_lt_clause(self) -> bool:
        return self.operator in (Operator.LessThan, Operator.LessThanOrEqualTo)

    def is_at_least_0_clause(self) -> bool:
        return self.operator is Operator.GreaterThanOrEqualTo and self.expected == 0

    def input_size_range(self, *, maximum: int) -> Iterator[int]:
        return input_size_range(self, maximum)

    def max_expected(self) -> Decimal:
        return self.expected


@attr.s(frozen=True, cache_hash=True, auto_attribs=True, slots=True)
class ConditionalAssertion:
    path: Tuple[str, ...]
    condition: SomePredicateExpression
    when_true: Assertion
    when_false: Optional[Assertion]

    @staticmethod
    def load(
        data: Dict[str, Any],
        *,
        c: Constants,
        ctx: 'RequirementContext',
        forbid: Sequence[Operator] = tuple(),
        path: List[str],
        data_type: DataType,
    ) -> 'ConditionalAssertion':
        condition = load_predicate_expression(data['$if'], ctx=ctx)

        when_true = load_single_assertion(data['$then'], c=c, ctx=ctx, forbid=forbid, path=[*path, '/t'], data_type=data_type)
        when_false = None
        if data.get('$else', None) is not None:
            when_false = load_single_assertion(data['$else'], c=c, ctx=ctx, forbid=forbid, path=[*path, '/f'], data_type=data_type)

        return ConditionalAssertion(
            condition=condition,
            when_true=when_true,
            when_false=when_false,
            path=tuple(path),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "assertion--if",
            "condition": self.condition.to_dict(),
            "when_true": self.when_true.to_dict(),
            "when_false": self.when_false.to_dict() if self.when_false else None,
        }

    def validate(self, *, ctx: 'RequirementContext') -> None:
        self.condition.validate(ctx=ctx)
        self.when_true.validate(ctx=ctx)
        if self.when_false:
            self.when_false.validate(ctx=ctx)

    def audit_and_resolve(self, data: Sequence['Clausable'] = tuple(), *, ctx: 'RequirementContext') -> 'SomeAssertion':
        if self.condition.result is True:
            when_true = self.when_true.audit_and_resolve(data, ctx=ctx)
            return attr.evolve(self, when_true=when_true)
        elif self.condition.result is False:
            if self.when_false:
                when_false = self.when_false.audit_and_resolve(data, ctx=ctx)
                return attr.evolve(self, when_false=when_false)
            else:
                return self
        # elif self.condition.result is None:
        else:
            raise Exception('conditional assertion condition not evaluated!')

    def evaluate_dynamic_conditions(self) -> SomeAssertion:
        # condition = self.condition.evaluate_dynamic()

        # return attr.evolve(self, condition=condition)
        raise Exception('uh oh')

    def status(self) -> ResultStatus:
        if self.condition.result is True:
            return self.when_true.status()
        elif self.condition.result is False and self.when_false:
            return self.when_false.status()
        else:
            return ResultStatus.Empty

    def rank(self) -> Tuple[Decimal, Decimal]:
        if self.condition.result is True:
            return self.when_true.rank()
        elif self.condition.result is False and self.when_false:
            return self.when_false.rank()
        else:
            return (ZERO_POINT_OH, ONE_POINT_OH)

    def max_expected(self) -> Decimal:
        if self.when_false:
            return max(self.when_true.expected, self.when_false.expected)
        return self.when_true.expected

    def input_size_range(self, *, maximum: int) -> Iterator[int]:
        if self.condition.result is True:
            return input_size_range(self.when_true, maximum)
        elif self.condition.result is False and self.when_false:
            return input_size_range(self.when_false, maximum)
        return input_size_range(self.when_true, maximum)

    def is_simple_count_clause(self) -> bool:
        if self.when_false is not None:
            return self.when_true.is_simple_count_clause() or self.when_false.is_simple_count_clause()
        return self.when_true.is_simple_count_clause()

    def is_simple_sum_clause(self) -> bool:
        if self.when_false is not None:
            return self.when_true.is_simple_sum_clause() or self.when_false.is_simple_sum_clause()
        return self.when_true.is_simple_sum_clause()

    def is_lt_clause(self) -> bool:
        if self.when_false is not None:
            return self.when_true.is_lt_clause() or self.when_false.is_lt_clause()
        return self.when_true.is_lt_clause()

    def is_at_least_0_clause(self) -> bool:
        if self.when_false is not None:
            return self.when_true.is_at_least_0_clause() or self.when_false.is_at_least_0_clause()
        return self.when_true.is_at_least_0_clause()


def evaluate_with_areas(assertion: Assertion, value: Sequence['AreaPointer']) -> Tuple[ResultStatus, AppliedClauseResult]:
    calculated_result = apply_clause_to_assertion_with_areas(assertion, value)

    computed_value = calculated_result.value
    operator_result = apply_operator(lhs=computed_value, op=assertion.operator, rhs=assertion.expected)

    if operator_result is True:
        result = ResultStatus.Done

    elif assertion.operator is Operator.GreaterThan and 0 < computed_value <= assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator is Operator.GreaterThanOrEqualTo and 0 < computed_value < assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator is Operator.EqualTo and 0 < computed_value < assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator in (Operator.LessThan, Operator.LessThanOrEqualTo):
        result = ResultStatus.FailedInvariant

    else:
        result = ResultStatus.Empty

    return (result, calculated_result)


def evaluate_with_items(assertion: Assertion, value: Sequence[Any]) -> Tuple[ResultStatus, AppliedClauseResult]:
    calculated_result = apply_clause_to_assertion_with_data(assertion, value)

    computed_value = calculated_result.value
    operator_result = apply_operator(lhs=computed_value, op=assertion.operator, rhs=assertion.expected)

    if operator_result is True:
        result = ResultStatus.Done

    elif assertion.operator is Operator.GreaterThan and 0 < computed_value <= assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator is Operator.GreaterThanOrEqualTo and 0 < computed_value < assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator is Operator.EqualTo and 0 < computed_value < assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator in (Operator.LessThan, Operator.LessThanOrEqualTo):
        result = ResultStatus.FailedInvariant

    else:
        result = ResultStatus.Empty

    return (result, calculated_result)


def evaluate_with_courses(assertion: Assertion, value: Sequence['CourseInstance']) -> Tuple[ResultStatus, AppliedClauseResult]:
    calculated_result = apply_clause_to_assertion_with_courses(assertion, value)
    operator_result = apply_operator(lhs=calculated_result.value, op=assertion.operator, rhs=assertion.expected)

    if operator_result is True:
        has_ip_courses = any(c.is_in_progress for c in calculated_result.courses)

        if has_ip_courses:
            # does the clause still pass if it's given only non-IP courses?
            non_ip_courses = (c for c in value if not c.is_in_progress)
            calculated_result_no_ip = apply_clause_to_assertion_with_courses(assertion, non_ip_courses)
            operator_result_no_ip = apply_operator(lhs=calculated_result_no_ip.value, op=assertion.operator, rhs=assertion.expected)
        else:
            # we don't need to check if there are no IP courses in the input
            operator_result_no_ip = True

        if assertion.treat_in_progress_as_pass or operator_result_no_ip is True:
            result = ResultStatus.Done

        elif has_ip_courses:
            has_enrolled_courses = any(c.is_in_progress_this_term for c in calculated_result.courses)
            has_registered_courses = any(c.is_in_progress_in_future for c in calculated_result.courses)
            has_incomplete_courses = any(c.is_incomplete for c in calculated_result.courses)

            # something has gone horribly wrong if there was an IP course that's neither
            # this term nor future, and isn't an incomplete
            assert has_enrolled_courses or has_registered_courses or has_incomplete_courses

            if (has_enrolled_courses or has_incomplete_courses) and (not has_registered_courses):
                result = ResultStatus.PendingCurrent
            elif has_registered_courses:
                result = ResultStatus.PendingRegistered
            else:
                raise Exception('unreachable')

        else:
            result = ResultStatus.Done

    elif assertion.operator is Operator.GreaterThan and 0 < calculated_result.value <= assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator is Operator.GreaterThanOrEqualTo and 0 < calculated_result.value < assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator is Operator.EqualTo and 0 < calculated_result.value < assertion.expected:
        result = ResultStatus.NeedsMoreItems

    elif assertion.operator in (Operator.LessThan, Operator.LessThanOrEqualTo):
        result = ResultStatus.FailedInvariant

    else:
        result = ResultStatus.Empty

    return (result, calculated_result)


def load_single_assertion(
    data: Dict[str, Any],
    *,
    c: Constants,
    ctx: 'RequirementContext',
    forbid: Sequence[Operator] = tuple(),
    path: Sequence[str],
    data_type: DataType,
) -> Assertion:
    path = tuple([*path, ".assert"])

    # where-clause
    where = None
    where_data = data.get('where', None)
    if where_data is not None:
        where = load_predicate(where_data, mode=data_type, c=c, ctx=ctx)

    # message and label
    message = data.get('message', None)
    if message is not None:
        assert type(message) == str

    label = data.get('label', None)
    if label is not None:
        assert type(label) == str

    # assertion body
    assertion = data['assert']

    assert len(assertion.keys()) == 1, "only one key allowed in single-clauses"
    key = list(assertion.keys())[0]

    if data_type is DataType.Course:
        assert key in course_actions
    elif data_type is DataType.Area:
        assert key in area_actions
    else:
        assert key in other_actions

    value = assertion[key]
    assert isinstance(value, Dict), TypeError(f'expected {value!r} to be a dictionary')

    operators = [k for k in value.keys() if Operator.is_operator(k)]
    assert len(operators) == 1, f"{value}"
    op = operators[0]
    operator = Operator(op)
    forbid = tuple({Operator.In, Operator.NotIn, *forbid})
    assert operator not in forbid, ValueError(f'operators {forbid} are forbidden here; got {operator!r}')

    assert '$ifs' not in value, KeyError('$ifs has been renamed to $changes')

    changes = tuple(
        ValueChange.load(cond, action=action, ctx=ctx)
        for cond, action in value.get('$changes', {}).items()
    )

    expected, original = load_expected_value(value=value, key=op, c=c)

    expected += compute_change_diff(changes)

    override_value = ctx.get_value_exception(path)
    if override_value:
        expected = override_value.value

    if expected == original:
        original = None

    # forbid all null values in tuples or single-value clauses
    assert expected is not None

    at_most = value.get('at_most', False)
    assert type(at_most) is bool

    overridden = True if ctx.get_waive_exception(path) is not None else False

    return Assertion(
        path=path,
        state=ResultStatus.Empty,
        data_type=data_type,
        where=where,
        evaluated=False,
        overridden=overridden,
        key=key,
        operator=operator,
        expected=expected,
        original=original,
        changes=changes,
        at_most=at_most,
        message=message,
        label=label,
        treat_in_progress_as_pass=value.get('treat_in_progress_as_pass', False),
    )


def load_expected_value(*, value: Dict, key: str, c: Constants) -> Tuple[Any, Any]:
    expected = value[key]
    if isinstance(expected, list):
        raise TypeError('lists are forbidden.')
    elif isinstance(expected, float):
        raise TypeError('float values are forbidden.')

    original = expected

    if type(expected) == str:
        expected = c.get_by_name(expected)
    elif isinstance(expected, Iterable):
        raise TypeError(f'unexpected type {type(expected)} for {expected!r}')

    allowed_types = {int}
    assert type(expected) in allowed_types, \
        ValueError(f"expected should be one of {allowed_types}, not {type(expected)}")

    return expected, original


def compute_change_diff(changes: Sequence[ValueChange]) -> Decimal:
    diff_value = Decimal(0)

    for change in changes:
        if not change.expression.result:
            continue

        if change.mode is ValueChangeMode.Add:
            diff_value += change.amount
        elif change.mode is ValueChangeMode.Subtract:
            diff_value -= change.amount
        else:
            raise TypeError(f'unsupported compute_change_diff mode {change.mode}')

    return diff_value


def input_size_range(assertion: Assertion, maximum: int) -> Iterator[int]:
    expected = int(assertion.expected)
    if assertion.expected != expected:
        raise TypeError(f'cannot find a range of values for a non-integer clause: {type(assertion.expected)}')

    if assertion.operator == Operator.EqualTo or (assertion.operator == Operator.GreaterThanOrEqualTo and assertion.at_most is True):
        if maximum < assertion.expected:
            yield maximum
            return
        yield from range(expected, expected + 1)

    elif assertion.operator == Operator.NotEqualTo:
        # from 0-maximum, skipping "expected"
        yield from range(0, expected)
        yield from range(expected + 1, max(expected + 1, maximum + 1))

    elif assertion.operator == Operator.GreaterThanOrEqualTo:
        if maximum < expected:
            yield maximum
            return
        yield from range(expected, max(expected + 1, maximum + 1))

    elif assertion.operator == Operator.GreaterThan:
        if maximum < expected:
            yield maximum
            return
        yield from range(expected + 1, max(expected + 2, maximum + 1))

    elif assertion.operator == Operator.LessThan:
        yield from range(0, expected)

    elif assertion.operator == Operator.LessThanOrEqualTo:
        yield from range(0, expected + 1)

    else:
        raise TypeError('unsupported operator for ranges %s', assertion.operator)
