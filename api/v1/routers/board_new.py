from typing_extensions import Annotated
from fastapi import APIRouter, Depends, Query, Body

from api.v1.models.response import responses
from service.board_new import BoardNewServiceAPI


router = APIRouter()


@router.get("/new",
            summary="최신 게시글 목록",
            responses={**responses}
            )
async def api_board_new_list(
    board_new_service: Annotated[BoardNewServiceAPI, Depends()],
    gr_id: str = Query(None),
    view: str = Query(None),
    mb_id: str = Query(None),
    current_page: int = Query(1, alias="page")
):
    """
    최신 게시글 목록
    """
    query = board_new_service.get_query(gr_id, mb_id, view)
    offset = board_new_service.get_offset(current_page)
    board_news = board_new_service.get_board_news(query, offset)
    total_count = board_new_service.get_total_count(query)
    board_new_service.arrange_borad_news_data(board_news, total_count, offset)

    content = {
        "total_count": total_count,
        "board_news": board_news,
        "current_page": current_page,
    }
    return content


@router.post("/new_delete",
            summary="최신 게시글을 삭제",
            responses={**responses}
             )
async def api_new_delete(
    board_new_service: Annotated[BoardNewServiceAPI, Depends()],
    bn_ids: list = Body(...),
):
    """
    최신 게시글을 삭제한다.
    """
    board_new_service.delete_board_news(bn_ids)
    return {"result": "deleted"}