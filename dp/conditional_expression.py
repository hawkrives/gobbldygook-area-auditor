"""Populates a CompoundPredicateExpression instance from an area specification.

Examples
========

> {has-ip-course: AMCON 101}
< PredicateExpression(
    function=has-ip-course,
    arguments=[AMCON 101],
    result=True,
)

> {$and: [{has-ip-course: AMCON 101}, {has-area-code: '130'}]}
< CompoundPredicateExpression(
    mode=.and,
    expressions=[
        PredicateExpression(
            function=has-ip-course,
            arguments=('AMCON 101',),
            result=True,
        ),
        PredicateExpression(
            function=has-area-code,
            arguments=('130',),
            result=False,
        ),
    ],
    result=False,
)
"""

from typing import Dict, Optional, Any, Mapping, Union, Tuple, TYPE_CHECKING
import logging
import enum

import attr

if TYPE_CHECKING:  # pragma: no cover
    from .context import RequirementContext

logger = logging.getLogger(__name__)

SomePredicateExpression = Union[
    'PredicateExpressionCompoundAnd',
    'PredicateExpressionCompoundOr',
    'PredicateExpressionNot',
    'PredicateExpression',
]


@enum.unique
class PredicateExpressionFunction(enum.Enum):
    HasIpCourse = 'has-ip-course'
    HasCompletedCourse = 'has-completed-course'
    HasCourse = 'has-course'
    PassedProficiencyExam = 'passed-proficiency-exam'
    HasDeclaredAreaCode = 'has-declared-area-code'
    RequirementIsSatisfied = 'requirement-is-satisfied'


STATIC_PREDICATE_FUNCTIONS = {
    PredicateExpressionFunction.HasDeclaredAreaCode,
    PredicateExpressionFunction.PassedProficiencyExam,
    PredicateExpressionFunction.HasCourse,
    PredicateExpressionFunction.HasCompletedCourse,
    PredicateExpressionFunction.HasIpCourse,
}


@attr.s(frozen=True, cache_hash=True, auto_attribs=True, slots=True)
class PredicateExpressionCompoundAnd:
    expressions: Tuple[SomePredicateExpression, ...] = tuple()
    result: Optional[bool] = None

    @staticmethod
    def can_load(data: Mapping) -> bool:
        return '$and' in data

    @staticmethod
    def load(data: Mapping, *, ctx: 'RequirementContext') -> 'PredicateExpressionCompoundAnd':
        # ensure that the data looks like {$and: []}, with no extra keys
        assert len(data.keys()) == 1
        assert type(data['$and']) == list
        clauses = tuple(load_predicate_expression(e, ctx=ctx) for e in data['$and'])
        return PredicateExpressionCompoundAnd(expressions=clauses, result=all(e.result for e in clauses))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "pred-expr--and",
            "expressions": [c.to_dict() for c in self.expressions],
            "result": self.result,
        }

    def validate(self, *, ctx: 'RequirementContext') -> None:
        for c in self.expressions:
            c.validate(ctx=ctx)

    def evaluate(self, *, ctx: 'RequirementContext') -> 'PredicateExpressionCompoundAnd':
        return attr.evolve(self, result=self.check(ctx=ctx))

    def check(self, *, ctx: 'RequirementContext') -> bool:
        return all(expression.evaluate(ctx=ctx) for expression in self.expressions)


@attr.s(frozen=True, cache_hash=True, auto_attribs=True, slots=True)
class PredicateExpressionCompoundOr:
    expressions: Tuple[SomePredicateExpression, ...] = tuple()
    result: Optional[bool] = None

    @staticmethod
    def can_load(data: Mapping) -> bool:
        return '$or' in data

    @staticmethod
    def load(data: Mapping, *, ctx: 'RequirementContext') -> 'PredicateExpressionCompoundOr':
        # ensure that the data looks like {$or: []}, with no extra keys
        assert len(data.keys()) == 1
        assert type(data['$or']) == list
        clauses = tuple(load_predicate_expression(e, ctx=ctx) for e in data['$or'])
        return PredicateExpressionCompoundOr(expressions=clauses, result=any(e.result for e in clauses))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "pred-expr--or",
            "expressions": [c.to_dict() for c in self.expressions],
            "result": self.result,
        }

    def validate(self, *, ctx: 'RequirementContext') -> None:
        for c in self.expressions:
            c.validate(ctx=ctx)

    def evaluate(self, *, ctx: 'RequirementContext') -> 'PredicateExpressionCompoundOr':
        return attr.evolve(self, result=self.check(ctx=ctx))

    def check(self, *, ctx: 'RequirementContext') -> bool:
        return any(expression.evaluate(ctx=ctx) for expression in self.expressions)


@attr.s(frozen=True, cache_hash=True, auto_attribs=True, slots=True)
class PredicateExpressionNot:
    expression: SomePredicateExpression
    result: Optional[bool] = None

    @staticmethod
    def can_load(data: Mapping) -> bool:
        return '$not' in data

    @staticmethod
    def load(data: Mapping, *, ctx: 'RequirementContext') -> 'PredicateExpressionNot':
        # ensure that the data looks like {$not: {}}, with no extra keys
        assert len(data.keys()) == 1
        expression = load_predicate_expression(data['$not'], ctx=ctx)
        return PredicateExpressionNot(expression=expression, result=expression.result)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "pred-expr--not",
            "expression": self.expression.to_dict(),
            "result": self.result,
        }

    def validate(self, *, ctx: 'RequirementContext') -> None:
        self.expression.validate(ctx=ctx)

    def evaluate(self, *, ctx: 'RequirementContext') -> 'PredicateExpressionNot':
        return attr.evolve(self, result=self.check(ctx=ctx))

    def check(self, *, ctx: 'RequirementContext') -> bool:
        return not self.expression.evaluate(ctx=ctx)


@attr.s(frozen=True, cache_hash=True, auto_attribs=True, slots=True)
class PredicateExpression:
    function: PredicateExpressionFunction
    # arguments: Tuple[Union[str, int, Decimal], ...]
    argument: str
    result: Optional[bool] = None

    @staticmethod
    def can_load(data: Mapping) -> bool:
        if len(data.keys()) != 1:
            return False

        try:
            function_name = list(data.keys())[0]
            PredicateExpressionFunction(function_name)
            return True
        except ValueError:
            return False

    @staticmethod
    def load(data: Mapping, *, ctx: 'RequirementContext') -> 'PredicateExpression':
        assert len(data.keys()) == 1, ValueError("only one key allowed in predicate expressions")

        function_name = list(data.keys())[0]
        function = PredicateExpressionFunction(function_name)

        argument = data[function_name]

        assert type(argument) is str, \
            TypeError(f'invalid argument type for predicate expression {type(argument)}')

        result = None
        if function in STATIC_PREDICATE_FUNCTIONS:
            result = evaluate_predicate_function(function, argument, ctx=ctx)

        return PredicateExpression(function=function, argument=argument, result=result)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "pred-expr",
            "function": self.function.value,
            "argument": self.argument,
            "result": self.result,
        }

    def validate(self, *, ctx: 'RequirementContext') -> None:
        pass

    def evaluate(self, *, ctx: 'RequirementContext') -> 'PredicateExpression':
        return attr.evolve(self, result=self.check(ctx=ctx))

    def check(self, *, ctx: 'RequirementContext') -> bool:
        return evaluate_predicate_function(self.function, self.argument, ctx=ctx)


def evaluate_predicate_function(function: PredicateExpressionFunction, argument: str, *, ctx: 'RequirementContext') -> bool:
    if function is PredicateExpressionFunction.HasDeclaredAreaCode:
        return ctx.has_declared_area_code(argument)

    elif function is PredicateExpressionFunction.HasCourse:
        return ctx.has_course(argument)

    elif function is PredicateExpressionFunction.HasIpCourse:
        return ctx.has_ip_course(argument)

    elif function is PredicateExpressionFunction.HasCompletedCourse:
        return ctx.has_completed_course(argument)

    elif function is PredicateExpressionFunction.PassedProficiencyExam:
        return ctx.music_proficiencies.passed_exam(of=argument)

    # elif function is PredicateExpressionFunction.RequirementIsSatisfied:
    #     return None

    else:
        raise TypeError(f"unknown static PredicateExpressionFunction {function}")


def load_predicate_expression(
    data: Mapping[str, Any],
    *,
    ctx: 'RequirementContext',
) -> SomePredicateExpression:
    """Processes a predicate expression dictionary into a CompoundPredicateExpression instance.

    > {has-ip-course: AMCON 101}
    > {$and: [{has-ip-course: AMCON 101}, {has-area-code: '130'}]}
    > {$or: [{has-ip-course: AMCON 101}, {has-ip-course: 'AMCON 102'}]}
    > {$not: {has-ip-course: AMCON 101}}
    > {$not: {$or: [{has-ip-course: AMCON 101}, {has-ip-course: 'AMCON 102'}]}}
    """

    if PredicateExpressionCompoundAnd.can_load(data):
        return PredicateExpressionCompoundAnd.load(data, ctx=ctx)

    elif PredicateExpressionCompoundOr.can_load(data):
        return PredicateExpressionCompoundOr.load(data, ctx=ctx)

    elif PredicateExpressionNot.can_load(data):
        return PredicateExpressionNot.load(data, ctx=ctx)

    elif PredicateExpression.can_load(data):
        return PredicateExpression.load(data, ctx=ctx)

    else:
        raise TypeError(f'unknown predicate expression {data!r}')