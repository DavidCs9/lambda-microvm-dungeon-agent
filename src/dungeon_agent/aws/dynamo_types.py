from collections.abc import Iterable, Mapping
from typing import Protocol


class DynamoDbExceptions(Protocol):
    ConditionalCheckFailedException: type[Exception]
    TransactionCanceledException: type[Exception]


class QueryPaginator(Protocol):
    def paginate(self, **kwargs: object) -> Iterable[Mapping[str, object]]: ...


class DynamoDbClient(Protocol):
    @property
    def exceptions(self) -> DynamoDbExceptions: ...

    def get_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def put_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def update_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def transact_write_items(self, **kwargs: object) -> Mapping[str, object]: ...

    def get_paginator(self, operation_name: str) -> QueryPaginator: ...
