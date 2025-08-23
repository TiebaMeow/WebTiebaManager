from pydantic import BaseModel


class ScanConfig(BaseModel):
    loop_cd: int = 10
    query_cd: float = 0.05
    pc_query_cd: float = 2
    operate_cd: float = 0.5
    thread_page_forward: int = 1
    post_page_forward: int = 1
    post_page_backward: int = 1
    comment_page_backward: int = 1
