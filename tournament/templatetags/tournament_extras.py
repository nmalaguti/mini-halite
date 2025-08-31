from django import template

register = template.Library()


@register.inclusion_tag("tournament/extras/bots_in_match.html")
def order_bots_by_results(match, bot=None):
    results = match.results.order_by("rank").all()
    return {
        "results": results,
        "bot": bot,
    }


@register.inclusion_tag("tournament/extras/page_links.html")
def page_links(page):
    return {
        "page": page,
    }


@register.inclusion_tag("tournament/extras/page_numbers.html")
def nearby_pages(page):
    neighbors = 5
    if page.number < (neighbors + 1):
        min_page = 1
        max_page = min((neighbors * 2 + 1), page.paginator.num_pages)
    elif page.number + (neighbors + 1) > page.paginator.num_pages:
        min_page = page.paginator.num_pages - (neighbors * 2)
        max_page = page.paginator.num_pages
    else:
        min_page = page.number - neighbors
        max_page = page.number + neighbors

    return {
        "page_numbers": range(
            max(1, min_page), min(max_page, page.paginator.num_pages) + 1
        ),
        "page": page,
    }
