from pydantic import BaseModel


class RuleInfo(BaseModel):
    """规则信息

    Attributes:
        type (str): 类型，如UserNameRule、IpRule等
        name (str): 用户友善的名称
        category (str): 分类，如用户、帖子等
        description (str): 描述
        series (str): 基本类型，如Text, Limiter
        values (dict[str, str] | None): 用于CheckBox/Select，提供给网页端信息 {原键: 用户友好名称}
    """

    type: str
    name: str
    category: str
    description: str
    series: str
    values: dict[str, str] | None = None
