"""Administrator review is an overlay; collector-owned publication flags stay intact."""

from sqlalchemy import and_, or_


def review_visibility(model):
    return and_(
        model.review_is_published.is_(True),
        or_(
            model.review_status == "legacy",
            and_(
                model.review_status == "approved",
                model.reviewed_content_sha256.is_not_distinct_from(
                    model.content_sha256
                ),
            ),
        ),
    )


def review_allows(row):
    # Server defaults appear only after flush; transient legacy objects have None.
    status = row.review_status or "legacy"
    visible = row.review_is_published
    return visible is not False and (
        status == "legacy"
        or (status == "approved" and row.reviewed_content_sha256 == row.content_sha256)
    )
