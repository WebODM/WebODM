from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class PageNumberPaginationWithPageSize(PageNumberPagination):
    """Expose the effective page size to API clients."""

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'page_size': self.page.paginator.per_page,
            'results': data,
        })
