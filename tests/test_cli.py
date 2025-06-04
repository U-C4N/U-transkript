import ast
import os
import pytest


def load_extract_video_id():
    path = os.path.join(os.path.dirname(__file__), "..", "cli.py")
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=path)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "extract_video_id":
            mod = ast.Module([node], type_ignores=[])
            code = compile(mod, path, "exec")
            ns = {}
            exec(code, ns)
            return ns["extract_video_id"]
    raise RuntimeError("extract_video_id not found")


extract_video_id = load_extract_video_id()


@pytest.mark.parametrize(
    "input_url, expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_extract_video_id_valid(input_url, expected):
    result = extract_video_id(input_url)
    assert result == expected
    assert len(result) == 11


def test_extract_video_id_invalid():
    with pytest.raises(ValueError):
        extract_video_id("https://example.com/")


