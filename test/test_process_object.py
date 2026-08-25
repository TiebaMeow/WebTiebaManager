"""P2-6：ProcessObject.copy() 保留 data 浅拷贝测试。"""

from types import SimpleNamespace

from src.schemas.process import ProcessObject


def test_copy_keeps_data_shallow_copy():
    content = SimpleNamespace(pid=1)
    data = {"user_info": {"uid": 1}, "flags": [1, 2]}
    obj = ProcessObject(content=content, data=data, dto="dto")

    copied = obj.copy()

    # content/dto 引用保持一致
    assert copied.content is content
    assert copied.dto == "dto"

    # data 保留，且为同一份浅拷贝内容（外层是新对象，嵌套对象共享引用）
    assert copied.data == data
    assert copied.data is not data
    assert copied.data["user_info"] is data["user_info"]

    # 修改拷贝外层不影响原对象
    copied.data["extra"] = 1
    assert "extra" not in data


def test_copy_without_data_keeps_empty():
    obj = ProcessObject(content=SimpleNamespace(pid=2))
    copied = obj.copy()
    assert copied.data == {}
