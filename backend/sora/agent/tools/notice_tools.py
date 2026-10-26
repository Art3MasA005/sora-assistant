"""The owner's university notice board."""

from __future__ import annotations

from pydantic import BaseModel, Field

from sora.agent.tools.base import ToolContext, registry
from sora.services import notices


class UniversityNoticesArgs(BaseModel):
    only_new: bool = Field(
        True, description="True: only notices the owner hasn't heard yet. False: the latest ones, heard or not."
    )
    limit: int = Field(5, ge=1, le=10, description="At most this many notices, newest first.")


@registry.tool(UniversityNoticesArgs, untrusted=True)
async def university_notices(ctx: ToolContext, a: UniversityNoticesArgs):
    """Check the owner's university notice board (Green University of Bangladesh) and read the notices: title,
    date, the notice's text (from its page and PDF; scanned PDFs have OCR typos — fix them when you read it out)
    and a link to the saved PDF. With only_new, notices returned are marked as heard, so ask once per question."""
    try:
        return await notices.check(only_new=a.only_new, limit=a.limit)
    except notices.NoticeError as exc:
        return f"Error: {exc}"
