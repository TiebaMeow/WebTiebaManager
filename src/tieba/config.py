from pydantic import BaseModel


class ScanConfig(BaseModel, extra="ignore"):
    loop_cd: int = 10
    query_cd: float = 0.05
    thread_page_forward: int = 1
    post_page_forward: int = 1
    post_page_backward: int = 1
    comment_page_backward: int = 1
